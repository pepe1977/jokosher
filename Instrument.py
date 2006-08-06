from Event import *
from CommandManager import *
import Project
import xml.dom.minidom as xml
import pygst
pygst.require("0.10")
import gst
import os
import time
from Monitored import *
from Utils import *
import gobject
import AddInstrumentDialog
import Globals
import shutil

#=========================================================================	

class Instrument(Monitored, CommandManaged):
	
	#_____________________________________________________________________
	
	def __init__(self, project, name, type, pixbuf, id=None):
		Monitored.__init__(self)
		
		self.project = project
		
		self.recordingbin = None
		
		self.path = ""
		self.events = []				# List of events attached to this instrument
		self.graveyard = []				# List of events that have been deleted (kept for undo)
		self.name = name				# Name of this instrument
		self.pixbuf = pixbuf			# The icon pixbuf resource
		self.isArmed = False			# True if the instrument is armed for recording
		self.isMuted = False			# True if the "mute" button is toggled on
		self.actuallyIsMuted = False		# True if the instrument is muted (silent)
		self.isSolo = False				# True if the instrument is solo'd (only instrument active)
		self.isVisible = True			# True if the instrument should be displayed in the mixer views
		self.level = 0.0				# Current audio level in range 0..1
		self.volume = 0.5				# Gain of the current instrument in range 0..1
		self.instrType = type				# The type of instrument
		self.effects = []				# List of GStreamer effect elements
		
		try:
			self.input = Globals.settings.recording["devicecardnum"]
		except:
			self.input =  "default"
		self.inTrack = None	# Mixer track to record from
		self.output = ""
		self.recordingbin = None
		self.id = project.GenerateUniqueID(id) #check is id is already being used before setting
		self.isSelected = False			# True if the instrument is currently selected
		
		# GStreamer pipeline elements for this instrument		
		self.volumeElement = gst.element_factory_make("volume", "Instrument_Volume_%d"%self.id)
		self.converterElement = gst.element_factory_make("audioconvert", "Instrument_Converter_%d"%self.id)
		#self.endConverterElement = gst.element_factory_make("audioconvert", "End_Instrument_Converter_%d"%self.id)
		self.levelElement = gst.element_factory_make("level", "Instrument_Level_%d"%self.id)
		self.levelElement.set_property("interval", gst.SECOND / 50)
		self.levelElement.set_property("message", True)
		self.levelElement.set_property("peak-ttl", 0)
		self.levelElement.set_property("peak-falloff", 20)

		self.playbackbin = gst.element_factory_make("bin", "Instrument_%d"%self.id)

		self.playbackbin.add(self.volumeElement)
		print "added volume (instrument)"

		self.playbackbin.add(self.levelElement)
		print "added level (instrument)"

		self.playbackbin.add(self.converterElement)
		print "added audioconvert (instrument)"

		self.effectsbin = gst.element_factory_make("bin", "InstrumentEffects_%d"%self.id)
		self.playbackbin.add(self.effectsbin)
		
		self.composition = gst.element_factory_make("gnlcomposition")

		# adding default source - this adds silence betweent the tracks
		self.silenceaudio = gst.element_factory_make("audiotestsrc")
		self.silenceaudio.set_property("volume", 0.0)
		
		self.silencesource = gst.element_factory_make("gnlsource")
		self.silencesource.set_property("priority", 1000)
		self.silencesource.set_property("start", 0)
		self.silencesource.set_property("duration", 1000 * gst.SECOND)
		self.silencesource.set_property("media-start", 0)
		self.silencesource.set_property("media-duration", 1000 * gst.SECOND)
		self.silencesource.add(self.silenceaudio)
		self.composition.add(self.silencesource)

		self.playbackbin.add(self.composition)
		print "added composition (instrument)"
		
		self.resample = gst.element_factory_make("audioresample")
		self.playbackbin.add(self.resample)
		print "added audioresample (instrument)"
		

		# link elements
		
		#self.converterElement.link(self.volumeElement)
		#print "linked instrument audioconvert to instrument volume"

		self.volumeElement.link(self.levelElement)
		print "linked instrument volume to instrument level"

		self.levelElement.link(self.resample)
		print "linked instrument level to instrument resample"
		
		self.playghostpad = gst.GhostPad("src", self.resample.get_pad("src"))
		self.playbackbin.add_pad(self.playghostpad)
		print "created ghostpad for instrument playbackbin"
	
		self.AddAndLinkPlaybackbin()

		self.composition.connect("pad-added", self.project.newPad, self)
		self.composition.connect("pad-removed", self.project.removePad, self)
		
		#mute this instrument if another one is solo
		self.OnMute()

		self.effectbinsrc = None
		self.effectbinsink = None
		
	#_____________________________________________________________________
	
	def __repr__(self):
		return "Instrument [%d] %s"%(self.id, self.name)
		
	#_____________________________________________________________________
		
	def StoreToXML(self, doc, parent, graveyard=False):
		if graveyard:
			ins = doc.createElement("DeadInstrument")
		else:
			ins = doc.createElement("Instrument")
		parent.appendChild(ins)
		ins.setAttribute("id", str(self.id))
		
		items = ["path", "name", "isArmed", 
				  "isMuted", "isSolo", "input", "output",
				  "isSelected", "isVisible", "inTrack", "instrType"]
		
		params = doc.createElement("Parameters")
		ins.appendChild(params)
		
		StoreParametersToXML(self, doc, params, items)
		
		for effect in self.effects:
			globaleffect = doc.createElement("GlobalEffect")
			globaleffect.setAttribute("element", effect.get_factory().get_name())
			ins.appendChild(globaleffect)
		
			propsdict = {}
			for prop in gobject.list_properties(effect):
				propsdict[prop.name] = effect.get_property(prop.name)
			
			StoreDictionaryToXML(self, doc, globaleffect, propsdict)
			
		for e in self.events:
			e.StoreToXML(doc, ins)
		for e in self.graveyard:
			e.StoreToXML(doc, ins, graveyard=True)
			
	#_____________________________________________________________________	
			
	def LoadFromXML(self, node):
		
		params = node.getElementsByTagName("Parameters")[0]
		
		LoadParametersFromXML(self, params)
		
		globaleffect = node.getElementsByTagName("GlobalEffect")
		
		for effect in globaleffect:
			elementname = str(effect.getAttribute("element"))
			print "Loading effect:", elementname
			instance = gst.element_factory_make(elementname, "effect")
			
			propsdict = LoadDictionaryFromXML(effect)
			for key, value in propsdict.iteritems():
				instance.set_property(key, value)		
			self.effects.append(instance)
			
		for ev in node.getElementsByTagName("Event"):
			try:
				id = int(ev.getAttribute("id"))
			except ValueError:
				id = None
			e = Event(self, None, id)
			e.LoadFromXML(ev)
			self.events.append(e)
	
		for ev in node.getElementsByTagName("DeadEvent"):
			try:
				id = int(ev.getAttribute("id"))
			except ValueError:
				id = None
			e = Event(self, None, id)
			e.LoadFromXML(ev)
			self.graveyard.append(e)
		
		#load image from file based on unique type
		#TODO replace this with proper cache manager
		for i in AddInstrumentDialog.getCachedInstruments():
			if self.instrType == i[1]:
				self.pixbuf = i[2]
				break
		if not self.pixbuf:
			print "Error, could not load image:", self.instrType
			
		#initialize the actuallyIsMuted variable
		self.checkActuallyIsMuted()

	#_____________________________________________________________________

	def addEffect(self, effect):
		'''Add instrument specific gstreamer elements'''
		self.effects += effect + " ! "
	
	#_____________________________________________________________________
	
	def record(self):
		'''Record to this instrument's temporary file.'''

		gst.debug("instrument recording")
		if self.input == "value":
			self.input = "default"

		#Set input channel on device mixer
		mixer = gst.element_factory_make('alsamixer')
		mixer.set_property("device", self.input)
		mixer.set_state(gst.STATE_READY)

		for track in mixer.list_tracks():
			if track.label == self.inTrack:
				mixer.set_record(track, True)
				break

		mixer.set_state(gst.STATE_NULL)
		
		#Create event file based on timestamp
		file = "%s_%d_%d.ogg"%(os.path.join(self.path, self.name.replace(" ", "_")), self.id, int(time.time()))
		self.tmpe = Event(self)
		self.tmpe.start = 0
		self.tmpe.name = "Recorded audio"
		self.tmpe.file = file

		self.output = "audioconvert ! vorbisenc ! oggmux ! filesink location=%s"%file.replace(" ", "\ ")
		print "Using pipeline: alsasrc device=%s%s"%(self.input, self.output)

		self.recordingbin = gst.parse_launch("bin.( alsasrc device=%s %s )"%(self.input, self.output))
		#We remove this instrument's playbin from the project so it doesn't try to record and play from the same file
		self.RemoveAndUnlinkPlaybackbin()
		self.project.mainpipeline.add(self.recordingbin)
		
	#_____________________________________________________________________


	def stop(self):
		if self.recordingbin:
			print "instrument stop"
			self.terminate()
			self.events.append(self.tmpe)
			self.tmpe.GenerateWaveform()
			self.temp = self.tmpe.id
			self.StateChanged()
			
	#_____________________________________________________________________

	def terminate(self):
		#Separated from stop so that instruments can be stopped without their events being kept (for terminating after errors)
		if self.recordingbin:
			self.project.mainpipeline.remove(self.recordingbin)
			self.recordingbin.set_state(gst.STATE_NULL)
			self.recordingbin = None
			#Relink playbackbin
			self.AddAndLinkPlaybackbin()
			self.StateChanged()

	#_____________________________________________________________________
	
	
	def addEventFromFile(self, start, file, copyfile=False):
		''' Adds an event to this instrument, and attaches the specified
			file to it. 
			
			start - The offset time in seconds
			file - file path
			copyfile - if True copy file to project audio dir
			
			undo : DeleteEvent(%(temp)d)
		'''
		
		if copyfile:
			audio_dir = os.path.join(os.path.split(self.project.projectfile)[0], "audio")
			basename = os.path.split(file.replace(" ", "_"))[1]
			basecomp = basename.rsplit('.',1)
			newfile = "%s_%d_%d.%s" % (basecomp[0], self.id, int(time.time()), basecomp[1])

			audio_file = os.path.join(audio_dir,newfile)
			shutil.copyfile(file,audio_file)
			file = audio_file
			name = basename
		else:
			name = file.split(os.sep)[-1]

		e = Event(self, file)
		e.start = start
		e.name = name
		self.events.append(e)
		e.GenerateWaveform()

		self.temp = e.id
		
		self.StateChanged()
		
	#_____________________________________________________________________
	
	def addEventFromEvent(self, start, event):
		"""Creates a new event instance identical to the event parameter 
		   and adds it to this instrument to this instrument (for paste functionality).
		      start - The offset time in seconds
		      event - The event to be recreated on this instrument
		      
		      undo : DeleteEvent(%(temp)d)
		"""
		e = Event(self, event.file)
		e.start = start
		for i in ["duration", "name", "offset"]:
			setattr(e, i, getattr(event, i))
		e.levels = event.levels[:]
		
		self.events.append(e)
		e.SetProperties()
		e.MoveButDoNotOverlap(e.start)
		
		self.temp = e.id
		self.StateChanged()
	
	#_____________________________________________________________________
	
	def DeleteEvent(self, eventid):
		'''Removes an event from this instrument. 
		   It does not register with undo or append it to the graveyard,
		   because both are done by event.Delete()
		'''
		event = [x for x in self.events if x.id == eventid][0]
		event.Delete()
	
	#_____________________________________________________________________

	def MultipleEventsSelected(self):
		''' Confirms whether or not multiple events are selected '''
		multiple = 0
		for ev in self.events:
			if (ev.isSelected):
				multiple += 1
		return (multiple > 1)

	#_____________________________________________________________________

	def JoinEvents(self):
		''' Joins together all the selected events into a single event '''

		eventsToJoin = []
		for ev in self.events:
			if (ev.isSelected):
				eventsToJoin.append(ev)

		# Move them next to each other
		joinPoint = eventsToJoin[0].start + eventsToJoin[0].duration
		for ev in eventsToJoin[1:]:
			ev.Move(ev.start, joinPoint)
			joinPoint = joinPoint + ev.duration

		# Join them into a single event
		while (len(eventsToJoin) > 1):
			eventsToJoin[0].Join(eventsToJoin[1].id)
			eventsToJoin.remove(eventsToJoin[1])
			
	#_____________________________________________________________________

	def SetLevel(self, level):
		""" Note that this sets the current REPORTED level, NOT THE VOLUME!
		"""
		self.level = level
	
	#_____________________________________________________________________

	def SetVolume(self, volume):
		"""Sets the volume of the instrument in the range 0..1
		"""
		self.volume = volume
		self.volumeElement.set_property("volume", volume)

	#_____________________________________________________________________
	
	def SetName(self, name):
		"""Sets the instrument to the given name
		   so it can be registered in the undo stack
		
		   undo : SetName("%(temp)s")
		"""
		self.temp = self.name
		self.name = name
		self.StateChanged()
	
	#_____________________________________________________________________
	
	def ToggleArmed(self):
		"""Toggles the instrument to be armed for recording
		
		   undo : ToggleArmed()
		"""
		self.isArmed = not self.isArmed
		self.StateChanged()
		
	#_____________________________________________________________________
	
	def ToggleMuted(self, wasSolo):
		"""Toggles the instrument to be muted
		
		   undo : ToggleMuted(%(temp)d)
		"""
		self.temp = self.isSolo
		self.isMuted = not self.isMuted
		if self.isSolo and not wasSolo:
			self.isSolo = False
			self.project.soloInstrCount -= 1
			self.project.OnAllInstrumentsMute()
		elif not self.isSolo and wasSolo:
			self.isSolo = True
			self.project.soloInstrCount += 1
			self.project.OnAllInstrumentsMute()
		else:
			self.OnMute()
			
		self.StateChanged()
	
	#_____________________________________________________________________
	
	def ToggleSolo(self, wasMuted):
		"""Toggles the all the other instruments muted
		
		   undo : ToggleSolo(%(temp)d)
		"""
		self.temp = self.isMuted
		self.isMuted = wasMuted
		
		if self.isSolo:
			self.isSolo = False
			self.project.soloInstrCount -= 1
		else:
			self.isSolo = True
			self.project.soloInstrCount += 1
		
		self.project.OnAllInstrumentsMute()
		self.StateChanged()
	
	#_____________________________________________________________________
	
	def SetVisible(self, visible):
		"""Sets wheather the instrument is minimized in CompactMixView
		
		   undo : SetVisible(%(temp)d)
		"""
		self.temp = self.isVisible
		self.isVisible = visible
		self.StateChanged()
	
	#_____________________________________________________________________
	
	def SetSelected(self, sel):
		"""Sets the instrument to be highlighted 
		   and receive keyboard actions
		"""
		self.isSelected = sel
		self.StateChanged()
	
	#_____________________________________________________________________
	
	def OnMute(self):
		self.checkActuallyIsMuted()
		if self.actuallyIsMuted:
			self.volumeElement.set_property("mute", True)
		else:
			self.volumeElement.set_property("mute", False)
	
	#_____________________________________________________________________
	
	def checkActuallyIsMuted(self):
		"""Determines if this intrument should be muted
		   by taking into account if any other intruments are muted
		"""
		if self.isMuted:
			self.actuallyIsMuted = True
		elif self.isSolo:
			self.actuallyIsMuted = False
		elif self.project.soloInstrCount > 0:
			self.actuallyIsMuted = True
		else:
			self.actuallyIsMuted = False
	
	#_____________________________________________________________________
	
	def AddAndLinkPlaybackbin(self):
		if not self.playbackbin in list(self.project.playbackbin.elements()):
			self.project.playbackbin.add(self.playbackbin)
			print "added instrument playbackbin to adder playbackbin"
		if not self.playghostpad.get_peer():
			self.playbackbin.link(self.project.adder)
			print "linked instrument playbackbin to adder (project)"

	#_____________________________________________________________________
	
	def RemoveAndUnlinkPlaybackbin(self):
		#get reference to pad before removing self.playbackbin from project.playbackbin!
		pad = self.playghostpad.get_peer()
		
		if self.playbackbin in list(self.project.playbackbin.elements()):
			self.project.playbackbin.remove(self.playbackbin)
			print "removed instrument playbackbin from project playbackbin"
		
		if pad:
			self.playbackbin.unlink(self.project.adder)
			self.project.adder.release_request_pad(pad)
			print "unlinked instrument playbackbin from adder"
	
	#_____________________________________________________________________

	def PrepareEffectsBin(self):	
		aclistnum = 1

		self.aclist = []

		numeffects = len(self.effects)

		for i in range(numeffects):
			aconvert = gst.element_factory_make("audioconvert", "EffectConverter_%d"%aclistnum)
			self.aclist.append(aconvert)
			aclistnum += 1
			
		print "LIST OF ACs"
		print self.aclist

		efflink = 1
		acnum = 0
		for effect in self.effects:	
			print "effect iter"
			self.effectsbin.add(effect)
			self.effectsbin.add(self.aclist[acnum])
			
			if efflink == 1:
				effect.link(self.aclist[acnum])
				efflink = 0
				print "link effect to audioconvert"
			else:
				self.aclist[acnum].link(effect)
				efflink = 1
				print "link audioconvert to effect"
			
			acnum += 1

		for pad in self.effects[0].pads():
			if pad.get_direction() == gst.PAD_SINK:
				self.effectsbinsink = gst.GhostPad("sink", pad)
				break

		for pad in self.aclist[-1].pads():
			if pad.get_direction() == gst.PAD_SRC:
				self.effectsbinsrc = gst.GhostPad("src", pad)
				break

		self.effectsbin.add_pad(self.effectsbinsink)
		self.effectsbin.add_pad(self.effectsbinsrc)
		
		print "PADS"
		print self.aclist[-1].get_pad("src")
		print self.effects[0].get_pad("Input")
		
#=========================================================================	

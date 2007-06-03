#
#	THIS FILE IS PART OF THE JOKOSHER PROJECT AND LICENSED UNDER THE GPL. SEE
#	THE 'COPYING' FILE FOR DETAILS
#
#	CompactMixView.py
#	
#	A sub-class of gtk.Frame containing the mixing view of the project
#
#-------------------------------------------------------------------------------

import gtk
import gobject
import RecordingView
from MixerStrip import *
from MasterMixerStrip import *
import gettext
_ = gettext.gettext

#=========================================================================

class CompactMixView(gtk.Frame):
	"""
	This class implements the mixing workspace view.
	"""
	
	""" Number of times a second the VUWidgets need updating. """
	FPS = 10
	
	#_____________________________________________________________________
	
	def __init__(self, project, mainview):
		"""
		Creates a new instance of CompactMixView.
		
		Parameters:
			project -- the active Project.
			mainview -- reference to the MainApp Jokosher window.
		"""
		gtk.Frame.__init__(self)
		self.project = project
		self.mainview = mainview
		self.channels = []
		self.lanes = []
		self.Updating = False
		self.CreateInstrBar()
		
		self.vbox = gtk.VBox()
		self.add(self.vbox)
		self.vpaned = gtk.VPaned()
		self.vbox.pack_start(self.vpaned, True, True)
		self.projectview = RecordingView.RecordingView(project, mainview, self, True)
		self.vpaned.add(self.projectview)
		self.hbox = gtk.HBox()
		self.vpaned.add(self.hbox)
		
		self.mastermixer = MasterMixerStrip(self.project, self, self.mainview)
		
		self.show_all()
		self.UpdateTimeout = False
		self.Update()
	#_____________________________________________________________________

	def CreateInstrBar(self):
		self.instrbar = gtk.Toolbar()
		self.instrbar.set_show_arrow(True)
		self.instrbar.set_style(gtk.TOOLBAR_BOTH_HORIZ)
		toollab = gtk.ToolItem()
		lab = gtk.Label()
		lab.set_markup(_("<b>Instruments Not Shown:</b>"))
		toollab.add(lab)
		toollab.set_is_important(True)
		self.instrbar.insert(toollab, 0)
	
	#_____________________________________________________________________
	
	def Update(self):
		"""
		Updates the mix view when requested by signal from project or __init__
		
		Returns:
			False -- indicates the GTK signal to:
					1) continue propagating the regular signal.
					2) stop calling the callback on a timeout_add.
		"""
		if self.Updating:
			return
		
		self.Updating = True
		
		# remove all the mixer strips and then add the visible ones
		for strip in self.hbox.get_children():
			self.hbox.remove(strip)
		
		for instr in self.project.instruments:
			if instr.isVisible:
				strip = None
				for channel in self.channels:
					if channel.instrument is instr:
						strip = channel
						strip.Update()
						break
				
				if not strip:
					strip = MixerStrip(self.project, instr, self, self.mainview)
					strip.connect("minimise", self.OnMinimiseTrack, instr)
					self.channels.append(strip)
					
				self.hbox.pack_start(strip, False, False)
		
		removeList = []
		for strip in self.channels:
			if not strip.instrument in self.project.instruments:
				strip.Destroy()
				removeList.append(strip)
		for item in removeList:
			self.channels.remove(item)
		del removeList
		
		#Pack the master vuwidget  
		self.hbox.pack_end(self.mastermixer, False, False)  			
		
		# Remove all minimized instruments from the toolbar
		for child in self.instrbar.get_children()[1:]:
			self.instrbar.remove(child)

		# add the minimised instruments to the minimised bar
		minimisedInstrs = [x for x in self.project.instruments if not x.isVisible]
		for instr in minimisedInstrs:
			toolbutt = gtk.ToolButton()
			
			imgsize = gtk.icon_size_lookup(gtk.ICON_SIZE_MENU)[0]
			pixbuf = instr.pixbuf.scale_simple(imgsize, imgsize, gtk.gdk.INTERP_BILINEAR)
			image = gtk.Image()
			image.set_from_pixbuf(pixbuf)
			
			toolbutt.set_label(instr.name)
			toolbutt.set_icon_widget(image)
			toolbutt.set_is_important(True)
			toolbutt.connect("clicked", self.OnMaximiseTrack, instr)
			
			self.instrbar.insert(toolbutt, -1)
		
		# Only show this toolbar if there is something minimized
		if minimisedInstrs and not self.instrbar.parent:
			self.vbox.pack_end(self.instrbar, False, True)
		elif not minimisedInstrs and self.instrbar.parent:
			self.vbox.remove(self.instrbar)
		
		self.show_all()
		self.Updating = False
		#for when being called from gobject thread
		return False
	#_____________________________________________________________________

	def OnMinimiseTrack(self, widget, instr):
		"""
		Minimizes a mixer strip (instrument).
		
		Parameters:
			widget -- reserved for GTK callbacks, don't use it explicitly.
			instr -- the Instrument to be hidden.
		"""
		instr.SetVisible(False)
		
	#_____________________________________________________________________

	def OnMaximiseTrack(self, widget, instr):
		"""
		Maximizes a mixer strip (instrument).
		
		Parameters:
			widget -- reserved for GTK callbacks, don't use it explicitly.
			instr -- the Instrument to be shown.
		"""
		instr.SetVisible(True)
	#_____________________________________________________________________
	
	def OnInstrumentSignal(self, instrument, extra=None):
		"""
		Callback for when a signal is emitted by instrument.
		
		Parameters:
			instrument -- the instrument instance that send the signal.
			extra -- extra parameters passed by the caller.
		"""
		self.Update()
		
	#_____________________________________________________________________
	
	def ConnectToInstrument(self, instrument):
		"""
		Connect the signal handlers in this class to the signals
		emitted by the given instrument instance.
		
		Parameters:
			instrument -- the instrument instance to connect to.
		"""
		instrument.connect("visible", self.OnInstrumentSignal)
	
	#_____________________________________________________________________
	
	def OnUpdateTimeout(self):
		"""
		Called at intervals (self.FPS) to update the VU meters.
		
		Returns:
			True -- keeps the timeout going during playback.
			False -- stops the timeout when playback stops.
		"""
		if self.mainview.isPlaying:
			self.mastermixer.vu.queue_draw()
			
			# redraw VU widgets for each instrument
			for mix in self.channels:
				mix.vu.queue_draw()
			
			return True
		else:
			# kill timeout when playback has stopped
			self.UpdateTimeout = False
			return False
	#_____________________________________________________________________
		
	def StartUpdateTimeout(self):
		""" 
		Initiates the OnUpdateTimeout - called from MainApp.play()
		when the play button is pressed.
		"""
		if not self.UpdateTimeout:
			gobject.timeout_add(int(1000 / self.FPS), self.OnUpdateTimeout, priority = gobject.PRIORITY_LOW)
			self.UpdateTimeout = True
	
#=========================================================================
		

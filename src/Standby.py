# pylint: skip-file
# flake8: noqa: disable-all

from os import path
from time import time

from enigma import eAVSwitch, eDVBVolumecontrol, eTimer, eDVBLocalTimeHandler, eServiceReference, eStreamServer, iRecordableService, quitMainloop

from Components.ActionMap import ActionMap
from Components.config import config, configfile
from Components.Console import Console
import Components.ParentalControl
from Components.SystemInfo import SystemInfo, BoxInfo
# BOXTYPE and MACHINENAME are no longer exported as module-level names on openATV
# (only BRAND/DISPLAYBRAND are); BoxInfo.getItem(...) is the one accessor both
# openATV and OpenViX provide for all four, so derive them from it directly.
BOXTYPE = BoxInfo.getItem("boxtype")
BRAND = BoxInfo.getItem("brand")
DISPLAYBRAND = BoxInfo.getItem("displaybrand")
MACHINENAME = BoxInfo.getItem("machinename")
from Components.Sources.StreamService import StreamServiceList
try:
	from Plugins.SystemPlugins.JobCockpit.JobSupervisor import JobSupervisor
	job_manager = JobSupervisor.getInstance()
except ImportError:
	from Components.Task import job_manager
try:
    from Plugins.SystemPlugins.CacheCockpit.FileManager import FileManager
except ImportError:
    FileManager = None
from GlobalActions import globalActionMap
import Screens.InfoBar
import Screens.Standby
from Screens.Screen import Screen, ScreenSummary
from Screens.MessageBox import MessageBox
try:
    # openATV's MessageBox defines MessageBoxSummary and unconditionally uses it as
    # its createSummary() result; OpenViX's MessageBox doesn't define this class at
    # all (its Screen.createSummary() defaults to None - no summary dialog is built,
    # so it never hits the crash this is worked around below).
    from Screens.MessageBox import MessageBoxSummary
except ImportError:
    MessageBoxSummary = None
import Tools.Notifications
from .RecordingUtils import isLiveRecordingOrRecordingSoon
from .__init__ import _

inStandby = None

QUIT_SHUTDOWN = 1
QUIT_REBOOT = 2
QUIT_RESTART = 3
QUIT_UPGRADE_FP = 4
QUIT_ERROR_RESTART = 5
QUIT_DEBUG_RESTART = 6
QUIT_ANDROID = 12
QUIT_KODI = 15
QUIT_MAINT = 16
QUIT_UPGRADE_PROGRAM = 42
QUIT_IMAGE_RESTORE = 43


def setLCDMiniTVMode(value):
	try:
		f = open("/proc/stb/lcd/mode", "w")
		f.write(value)
		f.close()
	except:
		pass


def sendCEC():
	print("[Standby][sendCEC] entered ")
	from enigma import eHdmiCEC  # noqa: E402
	msgaddress = 0x00
	cmd = 0x36  # 54 standby
	data = ""
	eHdmiCEC.getInstance().sendMessage(msgaddress, cmd, data, len(data))
	print("[Standby][sendCEC] departed ")


def lastPowerState(state):
	config.usage.power.last_known_state.value = state
	config.usage.power.last_known_state.save()
	configfile.save()


def isServiceProtected(ref):
	# OpenViX exposes a synchronous isProtected(ref); OpenATV only has the
	# callback/PIN-dialog driven isServicePlayable(), so there is no equivalent
	# side-effect-free check there. Treat "no isProtected" as "not protected"
	# rather than crashing (see PowerCockpit crash log 2026-08-21 02:55:46).
	isProtected = getattr(Components.ParentalControl.parentalControl, "isProtected", None)
	return bool(isProtected and isProtected(ref))


class Standby2(Screen):
	def Power(self):
		if BRAND in ('dinobot') or SystemInfo["HasHiSi"] or BOXTYPE in ("sfx6008", "sfx6018"):
			try:
				open("/proc/stb/hdmi/output", "w").write("on")
			except:
				pass
		print("[Standby] leave standby")
		self.close(True)

	def setMute(self):
		self.wasMuted = eDVBVolumecontrol.getInstance().isMuted()
		if not self.wasMuted:
			eDVBVolumecontrol.getInstance().volumeMute()

	def leaveMute(self):
		if not self.wasMuted:
			eDVBVolumecontrol.getInstance().volumeUnMute()

	def __init__(self, session):
		Screen.__init__(self, session)
		self.skinName = "Standby"

		print("[Standby] enter standby")

		if path.exists("/usr/scripts/standby_enter.sh"):
			Console().ePopen("/usr/scripts/standby_enter.sh")

		self["actions"] = ActionMap(["StandbyActions"],
		{
			"power": self.Power,
			"discrete_on": self.Power
		}, -1)

		globalActionMap.setEnabled(False)

		from Screens.InfoBar import InfoBar
		self.infoBarInstance = InfoBar.instance
		self.standbyStopServiceTimer = eTimer()
		self.standbyStopServiceTimer.callback.append(self.stopService)
		self.timeHandler = None

		self.setMute()

		if SystemInfo["Display"] and SystemInfo["LCDMiniTV"]:
			# set LCDminiTV off
			setLCDMiniTVMode("0")

		self.paused_service = self.paused_action = False

		self.prev_running_service = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		if isServiceProtected(self.prev_running_service):
			self.prev_running_service = eServiceReference(config.tv.lastservice.value)
		service = self.prev_running_service and self.prev_running_service.toString()
		if service:
			if service.rsplit(":", 1)[1].startswith("/"):
				self.paused_service = hasattr(self.session.current_dialog, "pauseService") and hasattr(self.session.current_dialog, "unPauseService") and self.session.current_dialog or self.infoBarInstance
				self.paused_action = hasattr(self.paused_service, "seekstate") and hasattr(self.paused_service, "SEEK_STATE_PLAY") and self.paused_service.seekstate == self.paused_service.SEEK_STATE_PLAY
				self.paused_action and self.paused_service.pauseService()
		if not self.paused_service:
			self.timeHandler = eDVBLocalTimeHandler.getInstance()
			if self.timeHandler.ready():
				if self.session.nav.getCurrentlyPlayingServiceOrGroup():
					self.stopService()
				else:
					self.standbyStopServiceTimer.startLongTimer(5)
				self.timeHandler = None
			else:
				self.timeHandler.m_timeUpdated.get().append(self.stopService)

		if hasattr(self.session, "pipshown") and self.session.pipshown:
			self.infoBarInstance and hasattr(self.infoBarInstance, "showPiP") and self.infoBarInstance.showPiP()

		if SystemInfo["ScartSwitch"]:
			self.setInput("SCART")
		else:
			self.setInput("AUX")
		if BRAND in ('dinobot') or SystemInfo["HasHiSi"] or BOXTYPE in ("sfx6008", "sfx6018"):
			try:
				open("/proc/stb/hdmi/output", "w").write("off")
			except:
				pass
		self.onFirstExecBegin.append(self.__onFirstExecBegin)
		self.onClose.append(self.__onClose)

	def __onClose(self):
		global inStandby
		inStandby = None
		Screens.Standby.inStandby = None
		lastPowerState("normal")
		self.standbyStopServiceTimer.stop()
		self.timeHandler and self.timeHandler.m_timeUpdated.get().remove(self.stopService)
		if self.paused_service:
			self.paused_action and self.paused_service.unPauseService()
		elif self.prev_running_service:
			if config.servicelist.startupservice_onstandby.value:
				self.session.nav.playService(eServiceReference(config.servicelist.startupservice.value))
				from Screens.InfoBar import InfoBar
				InfoBar.instance and InfoBar.instance.servicelist.correctChannelNumber()
			else:
				self.session.nav.playService(self.prev_running_service)
		self.session.screen["Standby"].boolean = False
		globalActionMap.setEnabled(True)
		self.setInput("ENCODER")
		self.leaveMute()
		if path.exists("/usr/scripts/standby_leave.sh"):
			Console().ePopen("/usr/scripts/standby_leave.sh")

	def __onFirstExecBegin(self):
		global inStandby
		inStandby = self
		Screens.Standby.inStandby = self
		lastPowerState("standby")
		self.session.screen["Standby"].boolean = True
		config.misc.standbyCounter.value += 1

	def createSummary(self):
		return StandbySummary

	def stopService(self):
		self.prev_running_service = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		if isServiceProtected(self.prev_running_service):
			self.prev_running_service = eServiceReference(config.tv.lastservice.value)
		self.session.nav.stopService()

	def setInput(self, input):
		INPUT = {
			"ENCODER": 0,
			"SCART": 1,
			"AUX": 2
		}
		eAVSwitch.getInstance().setInput(INPUT[input])


class Standby(Standby2):
	def __init__(self, session):
		if Screens.InfoBar.InfoBar and Screens.InfoBar.InfoBar.instance and Screens.InfoBar.InfoBar.ptsGetTimeshiftStatus(Screens.InfoBar.InfoBar.instance):
			self.skin = """<screen position="0,0" size="0,0"/>"""
			Screen.__init__(self, session)
			self.onFirstExecBegin.append(self.showMessageBox)
			self.onHide.append(self.close)
		else:
			Standby2.__init__(self, session)
		self.setTitle(_("Standby"))

	def showMessageBox(self):
		Screens.InfoBar.InfoBar.checkTimeshiftRunning(Screens.InfoBar.InfoBar.instance, self.showMessageBoxcallback)

	def showMessageBoxcallback(self, answer):
		if answer:
			self.onClose.append(self.doStandby)

	def doStandby(self):
		Tools.Notifications.AddNotification(Screens.Standby.Standby2)


class StandbySummary(ScreenSummary):
	skin = """
	<screen position="0,0" size="132,64">
		<widget source="global.CurrentTime" render="Label" position="0,0" size="132,64" font="Regular;40" halign="center">
			<convert type="ClockToText" />
		</widget>
		<widget source="session.RecordState" render="FixedLabel" text=" " position="0,0" size="132,64" zPosition="1" >
			<convert type="ConfigEntryTest">config.usage.blinking_display_clock_during_recording,True,CheckSourceBoolean</convert>
			<convert type="ConditionalShowHide">Blink</convert>
		</widget>
	</screen>"""


class QuitMainloopScreen(Screen):
	def __init__(self, session, retvalue=1):
		self.skin = """<screen name="QuitMainloopScreen" position="fill" flags="wfNoBorder">
				<ePixmap pixmap="icons/input_info.png" position="c-27,c-60" size="53,53" alphatest="on" />
				<widget name="text" position="center,c+5" size="720,100" font="Regular;22" halign="center" />
			</screen>"""
		Screen.__init__(self, session)

		from Components.Label import Label
		text = {
			QUIT_SHUTDOWN: _("Your %s %s is shutting down") % (DISPLAYBRAND, MACHINENAME),
			QUIT_REBOOT: _("Your %s %s is rebooting") % (DISPLAYBRAND, MACHINENAME),
			QUIT_RESTART: _("The user interface of your %s %s is restarting") % (DISPLAYBRAND, MACHINENAME),
			QUIT_KODI: _("The user interface of your %s %s will be stopped to run Kodi") % (DISPLAYBRAND, MACHINENAME),
			QUIT_ANDROID: _("Your %s %s is rebooting into Android Mode") % (DISPLAYBRAND, MACHINENAME),
			QUIT_MAINT: _("Your %s %s is rebooting into Recovery Mode") % (DISPLAYBRAND, MACHINENAME),
			QUIT_UPGRADE_FP: _("Your frontprocessor will be upgraded\nPlease wait until your %s %s reboots\nThis may take a few minutes") % (DISPLAYBRAND, MACHINENAME),
			QUIT_ERROR_RESTART: _("The user interface of your %s %s is restarting\ndue to an error in StartEnigma.py") % (DISPLAYBRAND, MACHINENAME),
			QUIT_UPGRADE_PROGRAM: _("Upgrade in progress\nPlease wait until your %s %s reboots\nThis may take a few minutes") % (DISPLAYBRAND, MACHINENAME),
			QUIT_IMAGE_RESTORE: _("Reflash in progress\nPlease wait until your %s %s reboots\nThis may take a few minutes") % (DISPLAYBRAND, MACHINENAME)
		}.get(retvalue)
		self["text"] = Label(text)


inTryQuitMainloop = False

deferredShutdown = None


class DeferredShutdown:
	"""Monitors active activities while in standby and shuts down when all are finished."""

	def __init__(self, session, retvalue):
		global deferredShutdown
		if deferredShutdown is not None:
			deferredShutdown.stop()
		self.session = session
		self.retval = retvalue
		self.wasInStandby = False
		self.checkTimer = eTimer()
		self.checkTimer.callback.append(self.checkActivities)
		self.checkTimer.start(10000)
		self.session.nav.record_event.append(self.getRecordEvent)
		deferredShutdown = self
		print("[Standby] DeferredShutdown: waiting for activities to finish before shutdown")

	def getRecordEvent(self, recservice, event):
		if event == iRecordableService.evEnd:
			if config.timeshift.isRecording.value:
				return
			self.checkActivities()

	def checkActivities(self):
		if inStandby is not None:
			self.wasInStandby = True
		elif self.wasInStandby:
			print("[Standby] DeferredShutdown: user left standby, cancelling deferred shutdown")
			self.stop()
			return

		if not self.wasInStandby:
			return

		recordings = isLiveRecordingOrRecordingSoon(self.session)  # self.session.nav.getRecordings()
		if recordings:
			return

		next_rec_time = self.session.nav.RecordTimer.getNextRecordingTime()
		if next_rec_time > 0 and (next_rec_time - time()) < 360:
			return

		jobs = [job for job in job_manager.getPendingJobs() if job.name != _('SoftcamCheck')]
		if jobs:
			return

		if eStreamServer.getInstance().getConnectedClients() or StreamServiceList:
			return

		print("[Standby] DeferredShutdown: all activities finished, shutting down")
		self.doShutdown()

	def stop(self):
		global deferredShutdown
		self.checkTimer.stop()
		try:
			self.session.nav.record_event.remove(self.getRecordEvent)
		except ValueError:
			pass
		deferredShutdown = None

	def doShutdown(self):
		self.stop()
		if config.hdmicec.enabled.value and self.retval == 1:
			sendCEC()
		if self.retval == 1:
			config.misc.DeepStandby.value = True
			if path.exists("/usr/scripts/standby_enter.sh"):
				Console().ePopen("/usr/scripts/standby_enter.sh")
		self.session.nav.stopService()
		lastPowerState("deep" if self.retval == QUIT_SHUTDOWN else "normal")
		print("[Standby] quitMainloop #1")
		if SystemInfo["Display"] and SystemInfo["LCDMiniTV"]:
			print("[Standby] LCDminiTV off")
			setLCDMiniTVMode("0")
		if BOXTYPE == "vusolo4k":
			f = open("/proc/stb/fp/oled_brightness", "w")
			f.write("0")
			f.close()
		quitMainloop(self.retval)


class TryQuitMainloop(MessageBox):
	def __init__(self, session, retvalue=1, timeout=-1, default_yes=True):
		self.retval = retvalue
		self.ptsmainloopvalue = retvalue
		if retvalue == QUIT_SHUTDOWN and FileManager is not None:
			if hasattr(config.plugins, "moviecockpit"):
				file_manager = FileManager.getInstance("MVC")
				if config.plugins.moviecockpit.trashcan_clean.value:
					file_manager.purgeTrashcan(config.plugins.moviecockpit.trashcan_retention.value)
				file_manager.archive()
		recordings = isLiveRecordingOrRecordingSoon(session)  # session.nav.getRecordings()
		jobs = []
		for job in job_manager.getPendingJobs():
			print(f"TryQuitMainloop: pending job: {job.name}")
			if job.name != _('SoftcamCheck'):
				jobs.append(job)
		print(f"TryQuitMainloop: {len(jobs)} pending jobs")

		inTimeshift = Screens.InfoBar.InfoBar and Screens.InfoBar.InfoBar.instance and Screens.InfoBar.InfoBar.ptsGetTimeshiftStatus(Screens.InfoBar.InfoBar.instance)
		self.connected = False
		reason = ""
		next_rec_time = -1
		if not recordings:
			next_rec_time = session.nav.RecordTimer.getNextRecordingTime()
		# config.usage.task_warning only exists on OpenViX (Components/UsageConfig.py);
		# openATV has no such toggle and always warns about pending jobs, so treat its
		# absence as "warning enabled" to match openATV's own native Standby.py behavior.
		if (not hasattr(config.usage, "task_warning") or config.usage.task_warning.value) and len(jobs):
			reason = (ngettext("%d job is running in the background!", "%d jobs are running in the background!", len(jobs)) % len(jobs)) + '\n'
		if inTimeshift:
			reason = _("You seem to be in timeshift!") + '\n'
		if recordings or (next_rec_time > 0 and (next_rec_time - time()) < 360):
			default_yes = False
			reason = _("Recording(s) are in progress or coming up in few seconds!") + '\n'
		if eStreamServer.getInstance().getConnectedClients() or StreamServiceList:
			reason += _("A client is streaming from this box!") + '\n'

		if reason and inStandby:
			if retvalue == QUIT_SHUTDOWN:
				DeferredShutdown(session, retvalue)
			self.isMessageBox = False
			self.skin = """<screen position="1310,0" size="0,0"/>"""
			Screen.__init__(self, session)
			self.close(False)
			return
		elif reason and not inStandby:
			if retvalue == QUIT_SHUTDOWN:
				if not config.plugins.powercockpit.show_idle_msg.value:
					# no message: go to standby right away and wait there until all activities are finished
					DeferredShutdown(session, retvalue)
					Tools.Notifications.AddNotification(Standby2)
					self.isMessageBox = False
					self.skin = """<screen position="1310,0" size="0,0"/>"""
					Screen.__init__(self, session)
					self.close(False)   # as the original: close() sends the HDMI-CEC standby message to the TV
					return
				text = reason + _("Entering standby. Shutdown will proceed when all activities are finished.")
				MessageBox.__init__(self, session, text, type=MessageBox.TYPE_INFO, timeout=5)
				self.skinName = "MessageBoxSimple"
				self.deferShutdown = True
				self.onShow.append(self.__onShow)
				self.onHide.append(self.__onHide)
				self.isMessageBox = True
				return
			text = {
				QUIT_REBOOT: _("Really reboot now?"),
				QUIT_RESTART: _("Really restart now?"),
				QUIT_KODI: _("Really start Kodi and stop user interface now?"),
				QUIT_ANDROID: _("Really reboot into Android Mode?"),
				QUIT_MAINT: _("Really reboot into Recovery Mode?"),
				QUIT_UPGRADE_FP: _("Really upgrade the frontprocessor and reboot now?"),
				QUIT_UPGRADE_PROGRAM: _("Really upgrade your %s %s and reboot now?") % (DISPLAYBRAND, MACHINENAME),
				QUIT_IMAGE_RESTORE: _("Really reflash your %s %s and reboot now?") % (DISPLAYBRAND, MACHINENAME)
			}.get(retvalue)
			if text:
				MessageBox.__init__(self, session, "%s\n%s" % (reason, text), type=MessageBox.TYPE_YESNO, timeout=timeout, default=default_yes)
				self.skinName = "MessageBoxSimple"
				session.nav.record_event.append(self.getRecordEvent)
				self.connected = True
				self.onShow.append(self.__onShow)
				self.onHide.append(self.__onHide)
				self.isMessageBox = True
				return
		self.isMessageBox = False
		self.skin = """<screen position="1310,0" size="0,0"/>"""
		Screen.__init__(self, session)
		self.close(True)

	def createSummary(self):
		# TryQuitMainloop can construct itself via either MessageBox.__init__ (a real
		# dialog, self.text set) or Screen.__init__ only (invisible passthrough, no
		# self.text) - openATV's session always builds a summary dialog regardless, so
		# it must pick a summary class matching which constructor actually ran,
		# mirroring openATV's own Screens/Standby.py:TryQuitMainloop.createSummary().
		# On OpenViX MessageBoxSummary doesn't exist and Screen.createSummary() already
		# returns None unconditionally (no summary is ever built there), so fall back
		# to that unchanged, pre-existing behavior instead of forcing ScreenSummary.
		if MessageBoxSummary is None:
			return Screen.createSummary(self)
		return MessageBoxSummary if self.isMessageBox else ScreenSummary

	def getRecordEvent(self, recservice, event):
		if event == iRecordableService.evEnd and config.timeshift.isRecording.value:
			return
		else:
			if event == iRecordableService.evEnd:
				recordings = isLiveRecordingOrRecordingSoon(self.session)  # self.session.nav.getRecordings()
				if not recordings:  # no more recordings exist
					rec_time = self.session.nav.RecordTimer.getNextRecordingTime()
					if rec_time > 0 and (rec_time - time()) < 360:
						self.initTimeout(360)  # wait for next starting timer
						self.startTimer()
					else:
						self.close(True)  # immediate shutdown
			elif event == iRecordableService.evStart:
				self.stopTimer()

	def close(self, value):
		if self.connected:
			self.connected = False
			self.session.nav.record_event.remove(self.getRecordEvent)
		if getattr(self, 'deferShutdown', False):
			self.deferShutdown = False
			if config.hdmicec.enabled.value and self.retval == 1:
				sendCEC()   # the TV goes to standby now, like with the shutdown itself (and not only if "Put TV in standby" is set)
			DeferredShutdown(self.session, self.retval)
			Tools.Notifications.AddNotification(Standby2)
			MessageBox.close(self, True)
			return
		if config.hdmicec.enabled.value and self.retval == 1:
			sendCEC()
		if value:
			self.hide()
			if self.retval == 1:
				config.misc.DeepStandby.value = True
				if path.exists("/usr/scripts/standby_enter.sh"):
					Console().ePopen("/usr/scripts/standby_enter.sh")
			self.session.nav.stopService()
			lastPowerState("deep" if self.retval == QUIT_SHUTDOWN else "normal")
			self.quitScreen = self.session.instantiateDialog(QuitMainloopScreen, retvalue=self.retval)
			self.quitScreen.show()
			print("[Standby] quitMainloop #1")
			if SystemInfo["Display"] and SystemInfo["LCDMiniTV"]:
				# set LCDminiTV off / fix a deep-standby-crash on some boxes / gb4k
				print("[Standby] LCDminiTV off")
				setLCDMiniTVMode("0")
			if BOXTYPE == "vusolo4k":  # workaround for white display flash
				f = open("/proc/stb/fp/oled_brightness", "w")
				f.write("0")
				f.close()
			quitMainloop(self.retval)
		else:
			MessageBox.close(self, True)

	def __onShow(self):
		global inTryQuitMainloop
		inTryQuitMainloop = True
		Screens.Standby.inTryQuitMainloop = True

	def __onHide(self):
		global inTryQuitMainloop
		inTryQuitMainloop = False
		Screens.Standby.inTryQuitMainloop = False

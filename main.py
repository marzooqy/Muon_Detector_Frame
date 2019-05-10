from PyQt5 import QtWidgets, uic, QtCore #pyqt is used for the gui
import skyfield.api #skyfield is used for the solar and lunar coordinates
import serial #serial is used to find, connect, write, and read to the arduino
import serial.tools.list_ports
import os
import time
import atexit
import sys

#can be changed if needed
latitude = '41.9295 N'
longitude = '88.7504 W'
tracking_refresh_rate = 5 * 60 #seconds

#the vendor and product ids of the arduino
vendor_id = 9025
product_id = 67

"""
list of elements in the main_window object:
radio buttons: manualRadio, solarRadio, LunarRadio
textboxes: altitudeBox, azimuthBox
spinBoxes: sunAltBox, sunAzBox, moonAltBox, moonAzBox
buttons: recalibrateButton, stopButton, setButton
labels: statusLabel
"""

"""
list of elements in the recalibration_window object:
buttons: leftAltButton, rightAltButton, leftAzButton, rightAzButton, stopButton, doneButton 
spinboxes: altSpinBox, azSpinBox
"""

#downloads the data that's used to find the coordinates, retrieves the solar and lunar coordinates, and tracks both the sun and the moon
#inherits QThread to make it run in a seperate a thread, running it in the main thread will freeze the gui
class Coordinates(QtCore.QThread):
	#the gui cannot be changed from within the thread, instead a signal should be sent to the main thread
	succeded = QtCore.pyqtSignal() #sent if the skyfield library data was opened or downloaded successfully
	failed = QtCore.pyqtSignal(str) #sent when an error occurs
	sent = QtCore.pyqtSignal(float, float) #sent when the coordinates are sent to the arduino, just to set the boxes text equal to the coordinates
	status_update = QtCore.pyqtSignal(str) #sent when the status bar needs to be updated

	def __init__(self):
		QtCore.QThread.__init__(self)
		
		#the tracker timer is used to send the sun's or moon's coordinates to the arduino every 5 minutes
		self.tracker = QtCore.QTimer()
		self.tracker.setInterval(tracking_refresh_rate * 1000)
		
	#the run method is the one method that actually runs in a seperate thread, any long task should be done here
	#the start method is the method (inherited from QThread) that should actually be used to run this method, this method should not be used
	def run(self):
		#sending a signal to the main thread to update the status bar
		self.status_update.emit('Downloading new coordinates data if needed...')
		
		#the first attempt to load the data, this one will connect to the internet to download the new data, if there is any
		try:
			#the path manipulation is added in case the program is run from another directory
			load = skyfield.api.Loader(os.path.join(os.path.dirname( __file__ ), 'skyfield_data'), verbose=False)
			planets = load('de421.bsp')
			
			self.ts = load.timescale() #an object that's used to retrieve the time
			self.sun = planets['sun']
			self.moon = planets['moon']
			self.position = planets['earth'] + skyfield.api.Topos(latitude, longitude) #topocentric position
			
			self.succeded.emit()
			
		#the second attempt, this one won' try to connect to the internet, it will just use the files that are available (less accurate ones)
		except(OSError, IOError):
			try:
				load = skyfield.api.Loader(os.path.join(os.path.dirname( __file__ ), 'skyfield_data'), verbose=False, expire=False)
				planets = load('de421.bsp')
				
				self.ts = load.timescale()
				self.earth = planets['earth']
				self.sun = planets['sun']
				self.moon = planets['moon']
				self.position = planets['earth'] + skyfield.api.Topos(latitude, longitude)
				
				#the failed signal is emitted just to display an error, the load attempt is actually successful if the program managed to get here
				self.failed.emit('Could not connect to the internet. Less accurate offline data will be used.')
				self.succeded.emit()
				
			#if the program is not able to access the files, or if they were removed and the program is unable to download them again, then the program won't work
			except(OSError, IOError):
				self.failed.emit('Could not connect to the internet to download the necessary data, and no offline data is found.')
				
	#used to retrieve the coordinates
	def get_coordinates(self, object):
		astrometric_position = self.position.at(self.ts.now()).observe(object)
		apparent_position = astrometric_position.apparent()
		altitude, azimuth, distance = apparent_position.altaz('standard')
		
		#the device shouldn't go below 0 degrees
		if altitude.degrees > 0:
			return altitude.degrees, azimuth.degrees
		else:
			return 0, azimuth.degrees
		
	def _track(self, object, added_alt, added_az):
		alt, az = self.get_coordinates(object)
		
		#adding the user input
		alt += added_alt
		az += added_az
		
		#the total altitude should be larger than 0 and less than 90
		if alt >= 0 and alt <= 90:
			#making the azimuth between 0 and 360
			if az < 0:
				az += 360
			
			if az >= 360:
				az -= 360
				
			connector.move(round(alt, 2), round(az, 2)) #sends the coordinates to the arduino
			self.sent.emit(alt, az) #updating the textboxes text with the coordinates
		
		#if it's not within the range, then stop tracking and send an error
		else:
			self.stop_tracking()
			if alt > 90:
				show_error('The total altitude is larger than 90.')
			else:
				show_error('The total altitude is less than 0.')
		
	#used to start tracking an object (the sun or the moon)
	def start_tracking(self, object, added_alt, added_az):
		#removing any functions that were connected to the tracker timer before adding a new one
		try:
			self.tracker.timeout.disconnect()
		except TypeError:
			pass
			
		self._track(object, added_alt, added_az) #the timer will only run after 5 minutes, so we should do this once
		#connecting the _track method to the timer, a lambda is used in order to ba able to add the argument 'object' to the method
		self.tracker.timeout.connect(lambda: self._track(object, added_alt, added_az))
		self.tracker.start()
		
	def stop_tracking(self):
		self.tracker.stop()
		
#--------------------------------------------------

#connects to the arduino, and sends signals to it
class Connector:
	def __init__(self):
		self.path = ''
		self.connected = False
		self.first_could_not_connect = True #used to make sure that the 'could not connect' error is only displayed once
		self.found = False
		self.first_not_found = True #used to display an error when the program is first lunched if the arduino is not connected
		
		self.checker = QtCore.QTimer()
		self.checker.timeout.connect(self.connect)
		self.checker.setInterval(2000)
		
	#looks for the arduino
	def find(self):
		for port in serial.tools.list_ports.comports():
			if port.vid == vendor_id and port.pid == product_id:
				self.found = True
				self.first_not_found = False
				self.path = port.device
				return
				
		self.found = False #this line will only run if the return statement doesn't run
		
	#this function is running all the time. it checks to see if the arduino is still connected, and also attempts to connect to it when it's not connected
	def connect(self):
		if not self.found and not self.connected:
			status.update('Looking for device...')		
			
		self.find()
		
		if self.first_not_found:
			set_gui(0)
			show_error('Could not find the device. Make sure that it is plugged in and recognized by the computer.')
			self.first_not_found = False
			
		elif self.found and not self.connected:
			try:
				status.update('Attempting to connect to the device...')
				self.arduino = serial.Serial(self.path, 9600, timeout=1)
				time.sleep(2) #should wait for 2 seconds for the arduino to reset
				
				set_gui(1) #enabling the gui
				status.update('The device has been connected.')
				
				self.connected = True
				
			except serial.serialutil.SerialException:
				if self.first_could_not_connect:
					set_gui(0)
					show_error('Could not connect to the device.')	
					self.first_could_not_connect = False
					
				else:
					set_gui(0)
				
		elif self.connected and not self.found:
			set_gui(0)
			show_error('The device has been disconnected.')
			
			self.first_could_not_connect = True #enabling this again to make it possible for the error to run again
			self.connected = False
			
	def start_checking(self):
		self.connect()
		self.checker.start()
		
	#writes data to the arduino
	def _write(self, command, alt, az):
		try:
			#this is the format that the arduino understands
			#command tells the arduino whether to move 'm', relative move 'c', stop 's', or reset 'r'
			message = bytes('<{} {} {}>'.format(command, alt, az), 'utf-8')
			self.arduino.write(message)
			
			print(message) #for debugging
			
		#this might never happen, but it's still there just in case
		except serial.serialutil.SerialException:
			set_gui(0)
			show_error('Could not send the information to the device.')
		
	def move(self, alt, az):
		self._write('m', alt, az)
		
	#used for recalibration
	def relative_move(self, alt, az): 
		self._write('c', alt, az)
		
	def stop_moving(self):
		self._write('s', 0, 0) #it doesn't matter what the alt and az is as this would just stop the device
		status.update('Stopped')
		
	#sets the coordinates saved in the Arduino to 0
	def reset_location(self):
		self._write('r', 0, 0) #it doesn't matter what the alt and az, the arduino will always reset the coordinates to zero
	
	#runs once the program is closed
	def close(self):
		if self.connected:
			self.arduino.close()
			
#--------------------------------------------------
			
#used to check the user input in both text boxes, will prevent the new input from being displayed if it's not what's expected
#if a spinbox is used instead of a normal text box, then this won't be needed
class Validator:
	#text_box is the box object that should be checked
	#max_value is the largest number that the user is allowed to input to the box
	#for the altitude that's 90, for the azimuth that's 359.9
	def __init__(self, text_box, max_value):
		self.text_box = text_box
		self.max_value = max_value
		self.old_text = self.text_box.text()
		
	def validate(self):
		new_text = self.text_box.text()
		
		#an empty string is allowed
		if new_text == '':
			self.old_text = new_text
		else:
			#if the input can't be converted to a float, then it's not a valid input (not a number)
			try:
				value = float(new_text)
				
				#if the input is within the expected range and has no decimal points then it's allowed
				#otherwise go back to the old input (old_text)
				if value >= 0 and value <= self.max_value and '.' not in new_text:
					self.old_text = new_text
				else:
					self.text_box.setText(self.old_text)
					
			except ValueError:
				self.text_box.setText(self.old_text)
				
#an object that manages the status bar
#the timer will run 5 seconds after the message is displayed (using update), and will remove the message
#QTimer is better than time.sleep because it's non-blocking and doesn't freeze the gui
class Status:
	def __init__(self):
		self.remover = QtCore.QTimer()
		self.remover.timeout.connect(self._remove)
		self.remover.setInterval(5000)
		
	def update(self, message):
		#should stop the running remover timer (if there is any) before displaying a new message
		#otherwise the message might be removed quickly
		self.remover.stop()
		main_window.statusLabel.setText(message)
		self.remover.start()
		
	def _remove(self):
		main_window.statusLabel.setText('')
		
#the function that runs when the set button is clicked
def set_button_clicked():
	if main_window.manualRadio.isChecked():
		if main_window.altitudeBox.text() == '' or main_window.azimuthBox.text() == '':
			show_error('One or both of the boxes are empty.')
			
		else:
			connector.move(main_window.altitudeBox.text(), main_window.azimuthBox.text()) #move the device to the user inputs
			
	elif main_window.solarRadio.isChecked():
		#start tracking the sun, updates every 5 minutes
		coordinates.start_tracking(coordinates.sun, main_window.sunAltBox.value(), main_window.sunAzBox.value())			
		
	else:
		coordinates.start_tracking(coordinates.moon, main_window.moonAltBox.value(), main_window.moonAzBox.value())
		
def stop_button_clicked():
	connector.stop_moving() #stop moving if the device is moving
	coordinates.stop_tracking() #stop tracking the sun or the moon if the device was in solar or lunar tracking mode
	
#used to costumize the set button
#enable_button enables or disables the button (similar to previous function)
#button_text sets the text of the button
#button_event is the function that would run if the button was clicked
def set_button(enable_button, button_text, button_event):
	main_window.setButton.setEnabled(enable_button)
	main_window.setButton.setText(button_text)
	
	#removing any functions that are attached to the button before adding the new function
	try:
		main_window.setButton.clicked.disconnect()
	except TypeError:
		pass
		
	main_window.setButton.clicked.connect(button_event)
	
#used to display an error, message is the error window's text
def show_error(message):
	QtWidgets.QMessageBox.warning(main_window, 'error', message, QtWidgets.QMessageBox.Ok)
	
#can be used to enable or disable the entire gui for recalibration_window
def set_recalibrate_gui(enable):
	recalibration_window.leftAltButton.setEnabled(enable)
	recalibration_window.rightAltButton.setEnabled(enable)
	recalibration_window.leftAzButton.setEnabled(enable)
	recalibration_window.rightAzButton.setEnabled(enable)
	recalibration_window.stopButton.setEnabled(enable)
	recalibration_window.doneButton.setEnabled(enable)
	
def set_gui(enable):
	#disabling the whole gui
	set_button(enable, 'Set', set_button_clicked)
	main_window.stopButton.setEnabled(enable)
	set_recalibrate_gui(enable)
	
#moves the device relatively by alt snd az
def recalibration_buttons_clicked(alt, az):
	connector.relative_move(alt, az)
	recalibration_window.doneButton.setEnabled(1)
	
#resets the coordinates saved in the arduino once the user is done recalibrating the device
def done_button_clicked():
	connector.reset_location()
	recalibration_window.doneButton.setEnabled(0)
	
#--------------------------------------------------
	
#runs when a succeded signal is emitted from the coordinates object (retrieved the data successfully)
def on_coordinates_success():
	set_gui(1)
	connector.start_checking() #starting to attempt to connect to the arduino here
	
#runs when a failed signal is emitted from the coordinates object
def on_coordinates_failure(message):
	#the pushButton will allow the user to try to download the data again when he has an internet connection
	#or when he resolves any issue that caused the unlikely-to-happen error
	set_button(1, 'Try Again', coordinates.start)
	show_error(message)
	
#runs when a sent signal is emitted from the arduino (when the sun's or moon's coordinates are sent to the arduino)
def on_coordinates_sent(alt, az):
	#setting the boxes to the sun's or moon's coordinates
	#displaying it with 0 decimal points
	main_window.altitudeBox.setText('{:.0f}'.format(alt))
	main_window.azimuthBox.setText('{:.0f}'.format(az))
	
#--------------------------------------------------
	
app = QtWidgets.QApplication([]) #starting an application

#loading the gui
#the gui files can be opened and edited using qt designer
main_window = uic.loadUi(os.path.join(os.path.dirname( __file__ ), 'main.ui'))
recalibration_window = uic.loadUi(os.path.join(os.path.dirname( __file__ ), 'recalibrate.ui'))

status = Status()
coordinates = Coordinates()
connector = Connector()

#disabling the gui before attempting to get the skyfield data files and connecting to the arduino
set_button(0, 'Set', set_button_clicked)
main_window.stopButton.setEnabled(0)
set_recalibrate_gui(0)

main_window.stopButton.clicked.connect(stop_button_clicked)

#clicking the recalibrate button will show the recalibration_window
main_window.recalibrateButton.clicked.connect(recalibration_window.show)

#creating validators to be used to check each box
altitude_validator = Validator(main_window.altitudeBox, 90)
azimuth_validator = Validator(main_window.azimuthBox, 359.9)

#the validate function will run whenever the text changes
main_window.altitudeBox.textChanged.connect(altitude_validator.validate)
main_window.azimuthBox.textChanged.connect(azimuth_validator.validate)

#clicking any of the four buttons will move the device relatively in different directions
recalibration_window.leftAltButton.clicked.connect(lambda: recalibration_buttons_clicked(-recalibration_window.altSpinBox.value(), 0))
recalibration_window.rightAltButton.clicked.connect(lambda: recalibration_buttons_clicked(recalibration_window.altSpinBox.value(), 0))
recalibration_window.leftAzButton.clicked.connect(lambda: recalibration_buttons_clicked(0, recalibration_window.azSpinBox.value()))
recalibration_window.rightAzButton.clicked.connect(lambda: recalibration_buttons_clicked(0, -recalibration_window.azSpinBox.value()))

#clicking the 'done' button will reset the location in the arduino
recalibration_window.doneButton.clicked.connect(done_button_clicked)
recalibration_window.stopButton.clicked.connect(stop_button_clicked)

#connecting the functions to the signals
coordinates.succeded.connect(on_coordinates_success)
coordinates.failed.connect(on_coordinates_failure)
coordinates.sent.connect(on_coordinates_sent)
coordinates.status_update.connect(status.update)

#displaying the main_window to the user, and starting the thread of the coordinates object (the run method)
main_window.show()
coordinates.start()

atexit.register(connector.close) #will close the connection with the arduino when the program is closed (if there is a connection)
sys.exit(app.exec()) #this line is necessory for pyqt to work
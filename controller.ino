/*
Copyright (C) 2018-2019 Husain Al Marzooq, Andre Ramos

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>
*/

#include <EEPROM.h>

/*missing: some transformations will need to be done to the altitude and azimuth, as they are not exactly the same as the actuators' angles
that will depend on the actuators' initial set up, and on whether the base actuator is going to move 180 or 360 degrees
we'll likely only have to do that later*/

/*the side actuator moves by a single step when a rising edge signal is sent to the pulse input
setting the direction input to HIGH tells the actuator to move forward when a pulse is sent to the +pulse input
setting it to LOW tells it to move backwards*/

int s_pul = 2; //the positive pulse/step output for the side actuator
int s_dir = 3; //the positive direction output for the side actuator
int s_delay = 11; //add comment here explaining why you chose this number
float s_step = 0.2; //the number of degrees that the side actuator moves on each step

int b_pul = 4; //the positive pulse/step output for the base actuator
int b_dir = 5; //the positive direction output for the base actuator
int b_delay = 50; //add comment here explaining why you chose this number
float b_step = 0.9; //the number of degrees that the base actuator moves on each step

int altLoc = 0; //the location of the altitude in the EEPROM storage
int azLoc = 4; //the location of the azimuth in the EEPROM storage

//a buffer to hold the data received from the arduino
const int buf_len = 20;
char buf[buf_len];
int numChars;

//stores the current position
float currentAlt;
float currentAz;

void setup() {
  pinMode(s_pul, OUTPUT);
  pinMode(s_dir, OUTPUT);
  pinMode(b_pul, OUTPUT);
  pinMode(b_dir, OUTPUT);
  
  digitalWrite(s_dir, HIGH);
  digitalWrite(b_dir, HIGH);
  
  Serial.begin(9600);
  
  //getting the current position of the actuator is saved in the arduino's EEPROM storage
  EEPROM.get(altLoc, currentAlt);
  EEPROM.get(azLoc, currentAz);
}

void loop() {
  if (Serial.available()) {
    //data format is "<x xx.xx xxx.xx>"
    
    Serial.readBytesUntil(' ', buf, buf_len);
    char command = buf[1];
    
    numChars = Serial.readBytesUntil(' ', buf, buf_len);
    buf[numChars] = '\0';
    float alt = roundAltitude(atof(buf)); //converting to a float and rounding
    
    numChars = Serial.readBytesUntil('>', buf, buf_len);
    buf[numChars] = '\0';
    float az = roundAzimuth(atof(buf)); //converting to a float and rounding
    
    // commands:
    // m: move
    // c: relative move
    // s: stop
    // r: reset
  
    if (command == 'm') {
      moveSide(alt - currentAlt);
      moveBase(az - currentAz);
      Serial.println("done"); //sending a message to the software to tell it that the device is done moving
    
    } else if (command == 'c') {
      moveSide(alt);
      moveBase(az);
    
    } else if (command == 'r') {
      currentAlt = 0;
      currentAz = 0;
      EEPROM.put(altLoc, currentAlt);
      EEPROM.put(azLoc, currentAz);
    }
  }
}

/*rounds the altitude to the closest multiple of 0.2 (the closest angle that the actuator can go to)
this is to prevent the actuator from accumulating small positioning errors over time*/
float roundAltitude(float angle) {
  return round(angle / s_step) * s_step;
}

/*similar to previous function*/
float roundAzimuth(float angle) {
  return round(angle / b_step) * b_step;
}

/*moves either actuator by one step, input should be the actuator's pulse/step pin*/
void step(int pin) {
  digitalWrite(pin, HIGH);
  delay(1);
  digitalWrite(pin, LOW);
}

/*moves the side actuator by degrees.*/
void moveSide(float degrees) {
  bool isPositive = degrees > 0;

  //if the degrees is larger than zero, then set the actuator to move forward, else set it to move backwards
  if (isPositive) {
    digitalWrite(s_dir, HIGH);
  } else {
    digitalWrite(s_dir, LOW);
    degrees = -degrees; //making degrees positive so it could be used in the loop
  }

  //move by the number of steps needed to reach the desired position
  float i = 0;
  for(i; i<degrees; i+=s_step) {
	  //if a stop signal is sent while moving, then stop moving
    if (Serial.available()) {
      Serial.readBytesUntil('>', buf, 20);
      if (buf[1] == 's') {
        break;
      }
    }
    
	  //moving
    delay(s_delay);
    step(s_pul);

    //debugging code
    //if (isPositive) { Serial.println(currentAlt + i); }
    //else { Serial.println(currentAlt - i); }
  }

  //set the current position equal to the new position and save it to the EEPROM
  if (isPositive) {
    currentAlt += i;
  } else {
    currentAlt -= i;
  }
  EEPROM.put(altLoc, currentAlt);
}

/*moves the base stepper by degrees.*/
void moveBase(float degrees) {
  bool isPositive = degrees > 0;

  //if degrees is larger than zero, then set the actuator to move forward, else set it to move backwards
  if (isPositive) {
    digitalWrite(b_dir, HIGH);
  } else {
    digitalWrite(b_dir, LOW);
    degrees = -degrees; //making degrees positive so it could be used in the loop
  }

  //move by the number of steps needed to reach the desired position
  float i = 0;
  for(i; i<degrees; i+=b_step) {
	//if a stop signal is sent while moving, then stop moving
    if (Serial.available()) {
      Serial.readBytesUntil('>', buf, 20);
      if (buf[1] == 's') {
        break;
      }
    }
    
	  //moving
    delay(b_delay);
    step(b_pul);
  
    //debugging code
    //if (isPositive) { Serial.println(currentAz + i); }
    //else { Serial.println(currentAz - i); }
  }

  //set the current position equal to the new position and save it to the EEPROM
  if (isPositive) {
    currentAz += i;
  } else {
    currentAz -= i;
  }
  EEPROM.put(azLoc, currentAz);
}

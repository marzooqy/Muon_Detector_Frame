#include <EEPROM.h>

/* Linear Motor control
 *  in1 COM = motor positive
 *  in2 COM = motor negative
 *  in1 NC (HIGH) = power negative
 *  in1 NO (LOW) = power positive
 *  in2 NC (HIGH) = power negative
 *  in2 NO (LOW) = power positive
 *  NOTE: ALWAYS go both HIGH before switching
 *  in1 LOW, in2 HIGH -> retract
 *  in1 HIGH, in2 LOW -> extend
*/


//Linear actuator constants
int lin_out1 = 2; // controls in1
int lin_out2 = 3; // controls in2
int lin_enable = 10; // controls vcc for relay
float s_step = 1;

//Rotary actuator constants
//with current driver, pins are on when LOW, off when HIGH
int b_pulse = 4;
int b_dir = 11;
int b_on = 8;
int ms2 = 6;
int ms1 = 7;
int b_delay = 20; //ms
float b_step = 1.8/8; //degrees

int altLoc = 0; //the location of the altitude in the EEPROM storage
int azLoc = 4; //the location of the azimuth in the EEPROM storage

//a buffer to hold the data received from the software
const int buf_len = 20;
char buf[buf_len];
int numChars;

//stores the current position
float currentAlt;
float currentAz;

float maxAlt = 80;

void setup() {
  pinMode(lin_out1, OUTPUT);
  pinMode(lin_out2, OUTPUT);
  digitalWrite(lin_out1, HIGH);
  digitalWrite(lin_out2, HIGH);

  // enable vcc after both relays are disabled (NC)
  pinMode(lin_enable, OUTPUT);
  digitalWrite(lin_enable, HIGH);

  pinMode(b_pulse, OUTPUT);
  pinMode(b_dir, OUTPUT);
  pinMode(ms2, OUTPUT);
  pinMode(ms1, OUTPUT);
  pinMode(b_on, OUTPUT);

  digitalWrite(b_dir, HIGH);
  digitalWrite(ms2, HIGH);
  digitalWrite(ms1, LOW);
  digitalWrite(b_on, LOW);

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
    float alt = roundAngle(atof(buf), s_step); //converting to a float and rounding
    
    numChars = Serial.readBytesUntil('>', buf, buf_len);
    buf[numChars] = '\0';
    float az = roundAngle(atof(buf), b_step); //converting to a float and rounding
    
    // commands:
    // m: move
    // c: relative move
    // s: stop
    // r: reset
    
    if (command == 'm') {
      //should not try going beyond what the actuator can go to
      if(alt > maxAlt) {
        alt = maxAlt;
      }

      //to prevent the wires from stretching, this will limit the range to [-180, 180]
      if (az > 180) {
        az -= 360;
      }

      moveSide(alt);
      moveBase(az - currentAz);
      
    } else if (command == 'c') {
      moveSideRelative(alt);
      moveBase(az);
      
    } else if (command == 'r') {
      currentAlt = 0;
      currentAz = 0;
      EEPROM.put(altLoc, currentAlt);
      EEPROM.put(azLoc, currentAz);
    }
  }
}

/*rounds the input to the closest angle that the actuator can go to*/
float roundAngle(float angle, float step) {
  return round(angle / step) * step;
}

/*provides an approximation for the amount of time needed to reach a specific altitude*/
float degToTime(float altitude) {
  return -0.00048*pow(altitude,4)+0.08357*pow(altitude,3)-4.68564*pow(altitude,2)+268.16505*altitude;
}

/*moves the linear actuator by input time
+time moves the actuator up
-time moves the actuator down*/
void moveLinearActuatorByTime(float time) {
  int pin;
  if(time >= 0) {
    pin = lin_out2;
  } else {
    pin = lin_out1;
    time = -time;
  }

  digitalWrite(pin, LOW);
  delay(time);
  digitalWrite(pin, HIGH);  
}

/*moves the linear actuator by degrees (relative)*/
void moveSideRelative(float degrees) {
  unsigned long time;
  int pin;
  if(degrees > 0) {
    time = 183.61053*degrees; //an approximation
    pin = lin_out2;
  } else {
    time = 183.61053*(-degrees);
    pin = lin_out1;
  }

  long currentTime = millis();
  
  digitalWrite(pin, LOW);

  //will stop if a signal is received, or if the elapsed time is > time
  while(!Serial.available() && time > (millis() - currentTime)) {}
  digitalWrite(pin, HIGH);  
}

/*moves the linear actuator by degrees (absolute)*/
void moveSide(float degrees) {
  if (degrees > currentAlt) {
    for(currentAlt; currentAlt < degrees; currentAlt += s_step) {
      if(Serial.available()) {
        break;
      }

      moveLinearActuatorByTime(round(degToTime(currentAlt + s_step) - degToTime(currentAlt)));

      //debugging code
      /*Serial.print("t: ");
      Serial.print(round(degToTime(currentAlt + s_step) - degToTime(currentAlt)));
      Serial.print(" theta: ");
      Serial.println(currentAlt + s_step);*/
    }
  }
  
  else if(degrees < currentAlt) {
    for(currentAlt; currentAlt > degrees; currentAlt -= s_step) {
      if(Serial.available()) {
        break;
      }

      moveLinearActuatorByTime(round(degToTime(currentAlt - s_step) - degToTime(currentAlt)));

      //debugging code
      /*Serial.print("t: ");
      Serial.print(round(degToTime(currentAlt - s_step) - degToTime(currentAlt)));
      Serial.print(" theta: ");
      Serial.println(currentAlt - s_step);*/
    }
  }

  //save new altitude to the EEPROM
  //Serial.println(currentAlt);
  EEPROM.put(altLoc, currentAlt);
}

/*moves the base stepper by degrees (relative)*/
void moveBase(float degrees) {
  bool isPositive = degrees > 0;
  if (isPositive) {
    digitalWrite(b_dir, HIGH);
  }
  else {
    degrees = -degrees;
    digitalWrite(b_dir, LOW);
  }
    
  //move by the number of steps needed to reach the desired position
  float i = 0;
  for(i; i<degrees; i+=b_step) {
	//if a stop signal is sent while moving, then stop moving
    if (Serial.available()) {
      break;
    }
    
    //moving
    delay(b_delay);
    digitalWrite(b_pulse, LOW);
    delay(1);
    digitalWrite(b_pulse, HIGH);
  
    //debugging code
    /*if (isPositive) {
      Serial.println(currentAz + i);
    } else {
      Serial.println(currentAz - i);
    }*/
  }

  //set the current position equal to the new position and save it to the EEPROM
  if (isPositive) {
    currentAz += i;
  } else {
    currentAz -= i;
  }
  EEPROM.put(azLoc, currentAz);
}

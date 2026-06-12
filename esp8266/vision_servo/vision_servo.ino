#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <Servo.h>

// --- Configuration ---
const char* ssid = "EdNet";
const char* password = "Huawei@123";

const char* mqtt_server = "157.173.101.159"; 
const int mqtt_port = 1883;
const char* client_id = "esp8266_team313";
const char* topic_movement = "benax/camera/control";

// Servo Configuration
Servo myServo;
const int servoPin = D5; 
int currentAngle = 90;   
int targetAngle = 90;

// Smoothing / search tuning
const int SERVO_MIN_ANGLE = 0;
const int SERVO_MAX_ANGLE = 180;
const int SERVO_STEP = 1;
const unsigned long SERVO_STEP_INTERVAL = 20;   // ms between small servo updates
const unsigned long SEARCH_HOLD_MIN_MS = 2000;  // dwell range at each search angle
const unsigned long SEARCH_HOLD_MAX_MS = 5000;
const int SEARCH_POSITIONS[] = {45, 70, 90, 110, 135};
const int SEARCH_POSITIONS_COUNT = sizeof(SEARCH_POSITIONS) / sizeof(SEARCH_POSITIONS[0]);

// --- Search Mode Variables ---
bool isSearching = true;         // Start in search mode by default
unsigned long lastServoStepTime = 0;
unsigned long searchDwellStart = 0;
int searchIndex = 0;

// --- Watchdog Timer Variables ---
unsigned long lastFaceDetectTime = 0;
const unsigned long FACE_TIMEOUT = 2000; // 2 seconds without a face triggers a search
unsigned long currentSearchHoldMs = 2500;

WiFiClient espClient;
PubSubClient client(espClient);

void setup_wifi() {
  delay(10);
  Serial.println("\nConnecting to WiFi...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");
}

void moveServo(int delta) {
  targetAngle += delta;
  if (targetAngle < SERVO_MIN_ANGLE) targetAngle = SERVO_MIN_ANGLE;
  if (targetAngle > SERVO_MAX_ANGLE) targetAngle = SERVO_MAX_ANGLE;
}

void setSearchMode(bool searching) {
  if (searching && !isSearching) {
    searchIndex = 0;
    targetAngle = SEARCH_POSITIONS[searchIndex];
    searchDwellStart = millis();
    currentSearchHoldMs = random(SEARCH_HOLD_MIN_MS, SEARCH_HOLD_MAX_MS + 1);
  }
  isSearching = searching;
}

void updateServoSmoothly(unsigned long now) {
  if (now - lastServoStepTime < SERVO_STEP_INTERVAL) {
    return;
  }

  if (currentAngle < targetAngle) {
    currentAngle += SERVO_STEP;
    if (currentAngle > targetAngle) currentAngle = targetAngle;
    myServo.write(currentAngle);
    lastServoStepTime = now;
  } else if (currentAngle > targetAngle) {
    currentAngle -= SERVO_STEP;
    if (currentAngle < targetAngle) currentAngle = targetAngle;
    myServo.write(currentAngle);
    lastServoStepTime = now;
  }
}

void callback(char* topic, byte* payload, unsigned int length) {
  String message = "";
  for (int i = 0; i < length; i++) {
    message += (char)payload[i];
  }
  
  // Parse the commands and update the Watchdog Timer
  if (message.indexOf("MOVE_LEFT") >= 0) {
    setSearchMode(false);
    lastFaceDetectTime = millis(); // Reset the timer!
    moveServo(-3);       
  } 
  else if (message.indexOf("MOVE_RIGHT") >= 0) {
    setSearchMode(false);
    lastFaceDetectTime = millis(); // Reset the timer!
    moveServo(3);        
  } 
  else if (message.indexOf("CENTERED") >= 0) {
    setSearchMode(false);
    lastFaceDetectTime = millis(); // Reset the timer!
  } 
  else if (message.indexOf("NO_FACE") >= 0) {
    setSearchMode(true);  // Explicit command to start searching
  }
  else if (message.indexOf("OUT_OF_FRAME") >= 0) {
    isSearching = false;
    currentAngle = 90;
    myServo.write(currentAngle);
  }
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection...");
    if (client.connect(client_id)) {
      Serial.println("Connected!");
      client.subscribe(topic_movement); 
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" trying again in 5s");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  myServo.attach(servoPin);
  myServo.write(currentAngle); 
  randomSeed(micros());

  setup_wifi();
  client.setServer(mqtt_server, mqtt_port);
  client.setCallback(callback);
  targetAngle = currentAngle;
  searchIndex = 0;
  searchDwellStart = millis();
  currentSearchHoldMs = random(SEARCH_HOLD_MIN_MS, SEARCH_HOLD_MAX_MS + 1);
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  unsigned long now = millis();

  // --- WATCHDOG TIMER ---
  // If we aren't currently searching, but it's been more than 2 seconds 
  // since we last saw a face, force the system back into search mode.
  if (!isSearching && (now - lastFaceDetectTime > FACE_TIMEOUT)) {
    Serial.println("Face lost! Watchdog triggered. Starting search...");
    setSearchMode(true);
  }

  // --- NON-BLOCKING SEARCH SWEEP ---
  if (isSearching) {
    if (currentAngle == targetAngle) {
      if (now - searchDwellStart >= currentSearchHoldMs) {
        searchIndex = (searchIndex + 1) % SEARCH_POSITIONS_COUNT;
        targetAngle = SEARCH_POSITIONS[searchIndex];
        searchDwellStart = now;
        currentSearchHoldMs = random(SEARCH_HOLD_MIN_MS, SEARCH_HOLD_MAX_MS + 1);
      }
    } else {
      updateServoSmoothly(now);
    }
  } else {
    updateServoSmoothly(now);
  }

  // --- SYSTEM HEARTBEAT ---
  static unsigned long lastHeartbeat = 0;
  if (now - lastHeartbeat > 5000) {
    lastHeartbeat = now;
    String heartbeat = "{\"node\": \"esp8266\", \"status\": \"ONLINE\"}";
    client.publish(topic_heartbeat, heartbeat.c_str());
  }
}

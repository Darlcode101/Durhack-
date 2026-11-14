// Bring-up 3: DFRobot touch (D2) and moisture (A0), powered from 3.3 V.
// PASS = touch prints 1 only while touched; moisture rises when you hold the probe with a damp finger.
void setup() { Monitor.begin(115200); pinMode(2, INPUT); }
void loop() {
  Monitor.print("touch="); Monitor.print(digitalRead(2));
  Monitor.print(" moisture="); Monitor.println(analogRead(A0));
  delay(200);
}

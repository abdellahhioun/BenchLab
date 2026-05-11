from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import sqlite3
import time
import uuid

# Import the same shared database logic [cite: 38-39]
from shared.database import get_connection, init_db

app = FastAPI(title="SignalWatch REST API")
init_db()

def _execute_with_retry(cursor, query: str, params: tuple):
    delay_s = 0.005
    for _ in range(400):
        try:
            cursor.execute(query, params)
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower():
                raise
            time.sleep(delay_s)
            delay_s = min(delay_s * 1.4, 0.05)
    cursor.execute(query, params)

# --- REST "Boxes" (Schemas) ---
# This is the REST version of your .proto messages
class SensorBase(BaseModel):
    name: str
    type: str
    location: str
    unit: str
    status: str
    last_value: Optional[float] = None

class Sensor(SensorBase):
    id: str
    created_at: str

# --- Endpoints [cite: 35-36] ---

@app.post("/sensors", response_model=Sensor)
def create_sensor(sensor: SensorBase):
    """POST /sensors - Create a new sensor."""
    conn = get_connection()
    cursor = conn.cursor()
    sensor_id = f"sensor_{uuid.uuid4().hex}"
    created_at = datetime.now().isoformat()
    
    _execute_with_retry(
        cursor,
        '''
            INSERT INTO sensors (id, name, type, location, unit, status, last_value, last_reading_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (sensor_id, sensor.name, sensor.type, sensor.location,
         sensor.unit, sensor.status, sensor.last_value, created_at, created_at),
    )
    
    conn.commit()
    conn.close()
    return {**sensor.dict(), "id": sensor_id, "created_at": created_at}

@app.get("/sensors/{sensor_id}", response_model=Sensor)
def get_sensor(sensor_id: str):
    """GET /sensors/{id} - Read one sensor."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sensors WHERE id = ?", (sensor_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Sensor not found")
    return dict(row)

@app.get("/sensors", response_model=List[Sensor])
def list_sensors():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sensors")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.put("/sensors/{sensor_id}", response_model=Sensor)
def update_sensor(sensor_id: str, sensor: SensorBase):
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()

    _execute_with_retry(
        cursor,
        """
            UPDATE sensors
            SET name = ?, type = ?, location = ?, unit = ?, status = ?, last_value = ?, last_reading_at = ?
            WHERE id = ?
        """,
        (sensor.name, sensor.type, sensor.location, sensor.unit, sensor.status, sensor.last_value, now_iso, sensor_id),
    )

    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Sensor not found")

    conn.commit()
    cursor.execute("SELECT * FROM sensors WHERE id = ?", (sensor_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Sensor not found")

    return dict(row)

@app.delete("/sensors/{sensor_id}")
def delete_sensor(sensor_id: str):
    """DELETE /sensors/{id}."""
    conn = get_connection()
    cursor = conn.cursor()
    _execute_with_retry(cursor, "DELETE FROM sensors WHERE id = ?", (sensor_id,))
    conn.commit()
    conn.close()
    return {"message": "Sensor deleted"}

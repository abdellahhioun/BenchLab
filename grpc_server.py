import grpc
from concurrent import futures
import time
from datetime import datetime
import uuid

# Import the files YOU generated!
import sensor_pb2
import sensor_pb2_grpc
# Import your shared database logic
from shared.database import get_connection, init_db

class SensorService(sensor_pb2_grpc.SensorServiceServicer):
    """This class implements the 'Actions' we defined in the .proto file."""

    def CreateSensor(self, request, context):
        """Action: Create a new sensor in the shared DB[cite: 36, 38]."""
        conn = get_connection()
        cursor = conn.cursor()
        
        sensor_id = f"sensor_{uuid.uuid4().hex}"
        now_iso = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT INTO sensors (id, name, type, location, unit, status, last_value, last_reading_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (sensor_id, request.name, str(request.type), request.location, 
              request.unit, str(request.status), request.last_value, now_iso, now_iso))
        
        conn.commit()
        conn.close()

        return sensor_pb2.Sensor(
            id=sensor_id,
            name=request.name,
            type=request.type,
            location=request.location,
            unit=request.unit,
            status=request.status,
            last_value=request.last_value
        )

    def GetSensor(self, request, context):
        """Action: Read one sensor by ID[cite: 36, 56]."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sensors WHERE id = ?", (request.id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return sensor_pb2.Sensor(
                id=row['id'], name=row['name'], type=int(row['type']),
                location=row['location'], unit=row['unit'], status=int(row['status'])
            )
        else:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Sensor not found")
            return sensor_pb2.Sensor()

    def ListSensors(self, request, context):
        """Action: Read all sensors[cite: 36]."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sensors")
        rows = cursor.fetchall()
        conn.close()

        sensor_list = []
        for row in rows:
            s = sensor_pb2.Sensor(
                id=row['id'], name=row['name'], type=int(row['type']),
                location=row['location'], unit=row['unit'], status=int(row['status'])
            )
            sensor_list.append(s)
        
        return sensor_pb2.SensorList(sensors=sensor_list)

    def UpdateSensor(self, request, context):
        """Action: Update an existing sensor[cite: 36]."""
        conn = get_connection()
        cursor = conn.cursor()
        now_iso = datetime.now().isoformat()
        cursor.execute('''
            UPDATE sensors
            SET name=?, type=?, location=?, unit=?, status=?, last_value=?, last_reading_at=?
            WHERE id=?
        ''', (request.name, str(request.type), request.location, request.unit, str(request.status),
              request.last_value, now_iso, request.id))
        conn.commit()
        conn.close()
        return request

    def DeleteSensor(self, request, context):
        """Action: Remove a sensor by ID[cite: 36]."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sensors WHERE id = ?", (request.id,))
        conn.commit()
        conn.close()
        return sensor_pb2.Empty()

def serve():
    """Starts the gRPC server engine[cite: 52]."""
    init_db()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    sensor_pb2_grpc.add_SensorServiceServicer_to_server(SensorService(), server)
    server.add_insecure_port('[::]:50051')
    print("SignalWatch gRPC Server active on port 50051...")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()

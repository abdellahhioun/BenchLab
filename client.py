import grpc
import sensor_pb2
import sensor_pb2_grpc

def run():
    # 1. Open a "Channel" to the server
    with grpc.insecure_channel('localhost:50051') as channel:
        # 2. Create a "Stub" (this is your local representative of the server)
        stub = sensor_pb2_grpc.SensorServiceStub(channel)

        print("--- Testing CreateSensor ---")
        # We fill the 'Create' envelope with data [cite: 21-32]
        new_sensor = sensor_pb2.CreateSensorRequest(
            name="Turbine-X1",
            type=sensor_pb2.TEMPERATURE,
            location="Section A-4",
            unit="°C",
            status=sensor_pb2.ACTIVE
        )
        response = stub.CreateSensor(new_sensor)
        print(f"Created Sensor ID: {response.id}")

        print("\n--- Testing ListSensors ---")
        # ListSensors takes an 'Empty' message as input [cite: 36]
        sensors = stub.ListSensors(sensor_pb2.Empty())
        for s in sensors.sensors:
            print(f"Found: {s.name} ({s.id}) at {s.location}")

        print("\n--- Testing GetSensor ---")
        # We use the ID we just created to look it up
        get_response = stub.GetSensor(sensor_pb2.SensorIdRequest(id=response.id))
        print(f"Retrieved: {get_response.name}, Status: {get_response.status}")

        print("\n--- Testing Delete ---")
        stub.DeleteSensor(sensor_pb2.SensorIdRequest(id=response.id))
        print("Sensor deleted successfully.")

if __name__ == '__main__':
    run()
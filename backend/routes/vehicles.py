from fastapi import APIRouter, HTTPException

from ..database import get_pool
from ..schemas import VehicleCreate

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])


@router.get("")
def list_vehicles(limit: int = 100):
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT vehicle_id, vehicle_number, vehicle_type, status, last_seen
                FROM vehicle ORDER BY vehicle_id DESC LIMIT %s
                """,
                (min(limit, 1000),),
            )
            return [
                {"id": r[0], "number": r[1], "type": r[2], "status": r[3],
                 "last_seen": r[4].isoformat() if r[4] else None}
                for r in cur.fetchall()
            ]


@router.post("")
def register_vehicle(body: VehicleCreate):
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO vehicle (vehicle_number, vehicle_type) VALUES (%s, %s) "
                    "RETURNING vehicle_id",
                    (body.vehicle_number, body.vehicle_type),
                )
                vid = int(cur.fetchone()[0])
            except Exception as exc:
                raise HTTPException(status_code=409, detail=str(exc))
            if body.vehicle_type == "car":
                cur.execute(
                    "INSERT INTO car_detail (vehicle_id, fuel_type, seating_capacity) "
                    "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (vid, body.fuel_type or "petrol", body.seating_capacity or 5),
                )
            elif body.vehicle_type == "bus":
                cur.execute(
                    "INSERT INTO bus_detail (vehicle_id, seating_capacity, route_number) "
                    "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (vid, body.seating_capacity or 40, body.route_number),
                )
            else:
                cur.execute(
                    "INSERT INTO emergency_vehicle_detail (vehicle_id, emergency_type) "
                    "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (vid, body.emergency_type or "ambulance"),
                )
    return {"vehicle_id": vid, "vehicle_number": body.vehicle_number}

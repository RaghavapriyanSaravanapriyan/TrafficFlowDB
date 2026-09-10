from fastapi import APIRouter, HTTPException

from ..database import get_pool
from ..schemas import RouteRequestIn
from ..services.route_optimizer import dijkstra, refresh_graph

router = APIRouter(prefix="/api/routes", tags=["routing"])


@router.post("/request")
def request_route(body: RouteRequestIn):
    if body.source_id == body.destination_id:
        raise HTTPException(status_code=422, detail="Source and destination must differ")
    with get_pool().connection() as conn:
        graph = refresh_graph(conn)
        if body.source_id not in graph["nodes"] or body.destination_id not in graph["nodes"]:
            raise HTTPException(status_code=404, detail="Unknown intersection")
        result = dijkstra(graph, body.source_id, body.destination_id,
                          priority=body.priority)
        if result is None:
            raise HTTPException(status_code=404, detail="No route found")
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO route_request
                    (source_intersection_id, destination_intersection_id, user_id)
                VALUES (%s, %s, %s) RETURNING request_id
                """,
                (body.source_id, body.destination_id, body.user_id),
            )
            req_id = int(cur.fetchone()[0])
            cur.execute(
                """
                INSERT INTO route (request_id, total_distance_km, estimated_time_min, traffic_score)
                VALUES (%s, %s, %s, %s) RETURNING route_id
                """,
                (req_id, result["total_distance_km"],
                 result["estimated_time_min"], result["traffic_score"]),
            )
            route_id = int(cur.fetchone()[0])
            for i, sid in enumerate(result["segment_path"], start=1):
                cur.execute(
                    "INSERT INTO route_segment (route_id, segment_id, sequence_number) "
                    "VALUES (%s, %s, %s)",
                    (route_id, sid, i),
                )
    src = graph["nodes"][body.source_id]["name"]
    dst = graph["nodes"][body.destination_id]["name"]
    return {"request_id": req_id, "route_id": route_id,
            "source": src, "destination": dst, **result}


@router.get("/history")
def history(limit: int = 20):
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.route_id, r.total_distance_km, r.estimated_time_min,
                       r.traffic_score, r.created_at,
                       i1.name, i2.name
                FROM route r
                JOIN route_request q ON q.request_id = r.request_id
                JOIN intersection i1 ON i1.intersection_id = q.source_intersection_id
                JOIN intersection i2 ON i2.intersection_id = q.destination_intersection_id
                ORDER BY r.route_id DESC LIMIT %s
                """,
                (min(limit, 100),),
            )
            return [
                {"route_id": x[0], "distance_km": x[1], "eta_min": x[2],
                 "traffic_score": x[3],
                 "created_at": x[4].isoformat() if x[4] else None,
                 "source": x[5], "destination": x[6]}
                for x in cur.fetchall()
            ]

"""Central configuration. All tunables come from the environment."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://traffic:trafficpass@localhost:5432/trafficflowdb"
    traffic_window_minutes: int = 5
    poll_seconds: float = 2.0

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

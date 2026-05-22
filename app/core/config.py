from pydantic import computed_field
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from dotenv import load_dotenv

load_dotenv()


class Conf(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )


class AppConfig(Conf):
    IS_PROD: bool = False


class CORSConfig(Conf):
    CORS_ORIGINS: list[str] = ["*"]
    CORS_METHODS: list[str] = ["*"]
    CORS_HEADERS: list[str] = ["*"]


class PostgresConfig(Conf):
    DB_B2C_SERVICE_HOST: str = "localhost"
    DB_B2C_SERVICE_PORT: int = 5432
    DB_B2C_SERVICE_NAME: str = "b2c_service"
    DB_B2C_SERVICE_USER: str = "b2c_user"
    DB_B2C_SERVICE_PASSWORD: str = "b2c_pass"
    ECHO: bool = False

    @computed_field
    @property
    def POSTGRES_URL_ASYNC(self) -> MultiHostUrl:
        return MultiHostUrl.build(
            scheme="postgresql+asyncpg",
            username=self.DB_B2C_SERVICE_USER,
            password=self.DB_B2C_SERVICE_PASSWORD,
            host=self.DB_B2C_SERVICE_HOST,
            port=self.DB_B2C_SERVICE_PORT,
            path=self.DB_B2C_SERVICE_NAME,
        )


class JwtConfig(Conf):
    JWT_SECRET_KEY: str = "changeme"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30


class RedisConfig(Conf):
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""

    @property
    def REDIS_URL_ASYNC(self) -> dict:
        return {
            "host": self.REDIS_HOST,
            "port": self.REDIS_PORT,
            "password": self.REDIS_PASSWORD,
            "decode_responses": True,
        }


class RabbitConfig(Conf):
    RABBITMQ_URL: str = "amqp://guest:guest@rabbitmq:5672/"
    ORDERS_RESERVED_ROUTING_KEY: str = "orders.reserved"
    PRODUCTS_RESERVE_ROUTING_KEY: str = "products.reserve"


class ServiceConfig(Conf):
    SERVICE_KEY: str = "internal-service-key"
    B2B_URL: str = "http://b2b:8010"
    NGINX_URL: str = "http://nginx_gateway"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    app: AppConfig = AppConfig()
    cors: CORSConfig = CORSConfig()
    pg_database: PostgresConfig = PostgresConfig()
    jwt: JwtConfig = JwtConfig()
    redis: RedisConfig = RedisConfig()
    rabbitmq: RabbitConfig = RabbitConfig()
    service: ServiceConfig = ServiceConfig()


settings = Settings()

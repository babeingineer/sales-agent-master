from fastapi import FastAPI
from app.db.database import Base, engine
from app.api.route import router as main_router


Base.metadata.create_all(bind=engine)
app = FastAPI()
app.include_router(main_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host = "0.0.0.0", port = 8001)
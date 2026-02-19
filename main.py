from fastapi import FastAPI
import models  # This imports your new models file

app = FastAPI()

# This command tells SQLAlchemy to create the tables in MySQL
models.Base.metadata.create_all(bind=models.engine)

@app.get("/")
def day_two():
    return {"status": "Tables Created", "message": "NutriCore Database structure is live!"}
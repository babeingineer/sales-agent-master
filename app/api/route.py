import json
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query, Form, Response, Request, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi_sqlalchemy import db
from passlib.context import CryptContext
from app.db.models.user import User
from app.db.models.campaign import Campaign
from app.db.models.contact import Contact
from app.db.database import SessionLocal
from sqlalchemy.orm import Session
from pydantic import BaseModel
from salesgpt.salesgptapi import SalesGPTAPI
from typing import List, Annotated
from twilio.rest import Client
from jose import JWTError, jwt
from twilio.twiml.voice_response import VoiceResponse
from langchain_community.chat_models import ChatLiteLLM
from salesgpt.agents import SalesGPT


router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


################################## User #####################################

SECRET_KEY = "4b8574baecf063d417c3ee348422ddd3e1b3120f33d742c63e3b1c1b17ce25c7"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def get_user(email: str, db):
    try:
        user = db.query(User).filter(User.email == email).one()
        return user
    except:
        return None

def authenticate_user(email: str, password: str, db):
    user = get_user(email, db)

    if not user:
        return False
    if not verify_password(password, user.password):
        return False
    return user

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=60)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user(email, db)
    if user is None:
        raise credentials_exception
    return user


class UserPayload(BaseModel):
    email: str
    password: str

@router.post("/signup")
async def user_signup(payload:UserPayload, db: Session = Depends(get_db)):
    try:
        user = User(email=payload.email, password=get_password_hash(payload.password))
        db.add(user)
        db.commit()
        return "Success"
    except:
        raise HTTPException(status_code=400, detail="Same Email or Database Error")

@router.post("/signin")
async def user_signin(payload:UserPayload, db: Session = Depends(get_db)):
    user = authenticate_user(payload.email, payload.password, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication Failed")
    return create_access_token({"sub": user.email})
    

################################## Campaign #####################################


class CampaignCreate(BaseModel):
    campaign_name: str
    salesperson_name: str
    salesperson_role: str
    company_name: str
    company_business: str
    company_values: str
    conversation_purpose: str
    conversation_type: str
    use_custom_prompt: bool
    custom_prompt: str
    twilio_sid: str
    twilio_token: str
    twilio_number: str

@router.post("/campaign")
def create_campaign(user: Annotated[User, Depends(get_current_user)], payload: CampaignCreate, db: Session = Depends(get_db)):
    payload_obj = payload.model_dump()
    campaign = Campaign(user_id=user.id, **payload_obj)
    db.add(campaign)
    db.commit()
    return campaign

@router.get("/campaigns")
def get_campaign(user: Annotated[User, Depends(get_current_user)], db: Session = Depends(get_db)):
    campaigns = db.query(Campaign).filter(Campaign.user_id == user.id).all()
    return campaigns

@router.get("/campaign/{campaign_id}")
def get_campaign(user: Annotated[User, Depends(get_current_user)], campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).one()
    return campaign


##################################### Contact #####################################
class ContactCreate(BaseModel):
    email: str
    phone_number: str
    name: str

@router.post("/contact")
def create_contact(user: Annotated[User, Depends(get_current_user)], payload: ContactCreate, campaign_id:str = Query(...), db: Session = Depends(get_db)):
    contact = Contact(campaign_id = campaign_id, email=payload.email, phone_number = payload.phone_number, name = payload.name)
    db.add(contact)
    db.commit()
    return contact

@router.get("/contacts")
def get_contact(user: Annotated[User, Depends(get_current_user)], campaign_id:str = Query(...), db: Session = Depends(get_db)):
    contacts = db.query(Contact).filter(Contact.campaign_id == campaign_id).all()
    return contacts


################################## Chat #####################################
llm = ChatLiteLLM(temperature=0.2, model_name="gpt-3.5-turbo-instruct")
sales_agents:dict[str, SalesGPT] = {}
# with open("69d32bcc-96d5-4b9f-b1f8-055d2be65337.json", "r", encoding="UTF-8") as f:
#     print("config loaded")
#     config = json.load(f)
# print(config)
# sales_agent = SalesGPT.from_llm(llm, **config)
# sales_agent.seed_agent()

@router.get("/chat")
async def chat(user: Annotated[User, Depends(get_current_user)], campaign_id:str = Query(...), contact_id:str = Query(...), db:Session = Depends(get_db)):
    contact: Contact = db.query(Contact).filter(Contact.id == contact_id).one()
    campaign: Campaign = db.query(Campaign).filter(Campaign.id == campaign_id).one()

    account_sid = campaign.twilio_sid
    auth_token = campaign.twilio_token
    twilio_number = campaign.twilio_number
    recipient_number = contact.phone_number

    config = {}
    config["salesperson_name"] = campaign.salesperson_name
    config["salesperson_role"] = campaign.salesperson_role
    config["company_name"] = campaign.company_name
    config["company_business"] = campaign.company_business
    config["company_values"] = campaign.company_values
    config["conversation_purpose"] = campaign.conversation_purpose
    config["conversation_type"] = campaign.conversation_type
    config["use_custom_prompt"] = campaign.use_custom_prompt
    config["custom_prompt"] = campaign.custom_prompt


    id = str(uuid.uuid4())
    sales_agents[id] = SalesGPT.from_llm(llm, **config)
    sales_agents[id].seed_agent()
    print("----------------------------------------------------------------")
    print(sales_agents)

    # Initialize Twilio client
    client = Client(account_sid, auth_token)
    call = client.calls.create(
        url=f"http://170.130.55.184:8001/twilio/voice?id={id}",  # URL where Twilio should send the call flow
        # url="http://demo.twilio.com/docs/voice.xml",  # URL where Twilio should send the call flow
        to=recipient_number,
        from_=twilio_number
    )
    return {"message": "Call initiated"}




@router.post("/twilio/voice")
async def twilio_voice(request:Request, id:str = Query(...)):
    form_data = await request.form()
    SpeechResult = form_data.get("SpeechResult")
    # Get the data from the incoming Twilio request
    
    # Create a TwiML response
    print(SpeechResult)
    if SpeechResult is not None:
        sales_agents[id].human_step(SpeechResult)
        print(SpeechResult)
    sales_agents[id].step()
    response = VoiceResponse()
    if len(sales_agents[id].conversation_history) == 0:
        response.say("hello")
    else:
        
        text = sales_agents[id].conversation_history[-1]
        colon_index = text.index(':')
        end_index = text.index('<')

        # Extract the text after ':' and before '<'
        desired_text = text[colon_index + 2:end_index]
        print(desired_text)
        response.say(desired_text)
    response.gather(input='speech', action=f'/twilio/voice?id={id}', speech_timeout='auto')
    # Return the TwiML response
    return Response(content=str(response), media_type="application/xml")






# class MessageList(BaseModel):
#     conversation_history: List[str]
#     human_say: str

# @router.post("/chat")
# async def chat_with_sales_agent(req: MessageList, campaign_id:str = Query(...), db: Session = Depends(get_db)):
#     # try:
#     campaign = db.query(Campaign).filter(Campaign.id == campaign_id).one()
#     sales_api = SalesGPTAPI(config_path=campaign.filename, verbose=True)
#     name, reply = sales_api.do(req.conversation_history, req.human_say)
#     res = {"name": name, "say": reply}
#     return res
#     # except:
#     #     return "failed"

import json
import uuid
from fastapi import APIRouter, Depends, Query, Form, Response, Request
from fastapi_sqlalchemy import db
from app.db.models.user import User
from app.db.models.campaign import Campaign
from app.db.models.contact import Contact
from app.db.database import SessionLocal
from sqlalchemy.orm import Session
from pydantic import BaseModel
from salesgpt.salesgptapi import SalesGPTAPI
from typing import List
from twilio.rest import Client
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


class UserPayload(BaseModel):
    email: str
    password: str

@router.post("/signup")
async def user_signup(payload:UserPayload, db: Session = Depends(get_db)):
    user = User(email=payload.email, password=payload.password)
    db.add(user)
    db.commit()
    return 100

@router.post("/signin")
async def user_signin(payload:UserPayload, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.email == payload.email).one()
        if user.password == payload.password:
            return "Sucess"
        return "Password Failed"
    except:
        return "No User"
    


class CampaignCreate(BaseModel):
    campaign_name: str
    salesperson_name: str
    salesperson_role: str
    company_name: str
    company_business: str
    company_values: str
    conversation_purpose: str
    conversation_type: str
    use_custom_prompt: str
    custom_prompt: str

@router.post("/{user_id}/campaign")
def create_campaign(user_id:int, payload: CampaignCreate, db: Session = Depends(get_db)):
    payload_obj = payload.model_dump()
    campaign_name = payload_obj.pop("campaign_name")
    data = json.dumps(payload_obj)
    filename = str(uuid.uuid4()) + ".json"
    file = open(filename, "w")
    file.write(data)
    file.close()
    campaign = Campaign(user_id=user_id, name=campaign_name, filename=filename)
    db.add(campaign)
    db.commit()
    return campaign

@router.get("/{user_id}/campaign")
def get_campaign(user_id:int, payload: CampaignCreate, db: Session = Depends(get_db)):
    campaigns = db.query(Campaign).filter(Campaign.user_id == user_id).all()
    return campaigns



class ContactCreate(BaseModel):
    email: str
    phone_number: str
    name: str

@router.post("/contact")
def create_contact(payload: ContactCreate, campaign_id:str = Query(...), db: Session = Depends(get_db)):
    contact = Contact(campaign_id = campaign_id, email=payload.email, phone_number = payload.phone_number, name = payload.name)
    db.add(contact)
    db.commit()
    return contact

@router.get("/contact")
def get_contact(campaign_id:str = Query(...), db: Session = Depends(get_db)):
    contacts = db.query(Contact).filter(Contact.campaign_id == campaign_id).all()
    return contacts


@router.get("/chat")
async def chat():
    account_sid = 'AC6b751dd057ab8767cada0f14da57a91f'
    auth_token = '450967db305c89974961d2c31d1be726'
    twilio_number = '+12898156204'
    recipient_number = '+13044609990'

    # Initialize Twilio client
    client = Client(account_sid, auth_token)
    call = client.calls.create(
        url="http://170.130.55.184:8001/twilio/voice",  # URL where Twilio should send the call flow
        # url="http://demo.twilio.com/docs/voice.xml",  # URL where Twilio should send the call flow
        to=recipient_number,
        from_=twilio_number
    )
    return {"message": "Call initiated"}


llm = ChatLiteLLM(temperature=0.2, model_name="gpt-3.5-turbo-instruct")
with open("69d32bcc-96d5-4b9f-b1f8-055d2be65337.json", "r", encoding="UTF-8") as f:
    print("config loaded")
    config = json.load(f)
sales_agent = SalesGPT.from_llm(llm, **config)
sales_agent.seed_agent()

@router.post("/twilio/voice")
async def twilio_voice(request:Request):
    form_data = await request.form()
    SpeechResult = form_data.get("SpeechResult")
    # Get the data from the incoming Twilio request
    
    # Create a TwiML response
    print(SpeechResult)
    if SpeechResult is not None:
        sales_agent.human_step(SpeechResult)
        print(SpeechResult)
    sales_agent.step()
    response = VoiceResponse()
    if len(sales_agent.conversation_history) == 0:
        response.say("hello")
    else:
        
        text = sales_agent.conversation_history[-1]
        colon_index = text.index(':')
        end_index = text.index('<')

        # Extract the text after ':' and before '<'
        desired_text = text[colon_index + 2:end_index]
        print(desired_text)
        response.say(desired_text)
    response.gather(input='speech', action='/twilio/voice', speech_timeout='auto')
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

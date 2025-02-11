from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, BackgroundTasks, status, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import uvicorn
import uuid

from .models.database import get_db, Conversation
from .services.audio_processing import process_audio_file
from .services.transcription import transcribe_audio
from .services.classification import classify_dialogue
from .services.speaker_identification import SpeakerIdentifier
from .services.progress import progress_tracker
from .services.search import SearchService
from .schemas.conversation import ConversationCreate, ConversationResponse

app = FastAPI(title="Sales Conversation Analysis System")

# CORS middleware for web interface
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

speaker_identifier = SpeakerIdentifier()

@app.post("/upload/single", response_model=ConversationResponse)
async def upload_single_audio(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    try:
        # Generate unique filename
        filename = f"{uuid.uuid4()}{file.filename}"
        
        # Save file
        file_location = f"uploads/{filename}"
        with open(file_location, "wb+") as file_object:
            file_object.write(await file.read())
        
        # Create conversation record
        conversation = Conversation(
            audio_path=file_location,
            status="processing"
        )
        db.add(conversation)
        db.commit()
        
        # Start background transcription task
        background_tasks.add_task(transcribe_and_analyze, conversation.id, file_location, db)
        
        return {"id": conversation.id, "status": "processing"}
        
        
        # Start background processing
        background_tasks.add_task(
            transcribe_and_analyze,
            conversation.id,
            file_location,
            db
        )
        
        return conversation
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def transcribe_and_analyze(
    conversation_id: int,
    file_path: str,
    db: Session
):
    try:
        # Get conversation from database
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conversation:
            raise ValueError(f"Conversation {conversation_id} not found")

        # Transcribe audio
        transcript = await transcribe_audio(file_path)
        
        # Update conversation with transcript
        conversation.transcript = transcript["text"]
        conversation.segments = transcript["segments"]
        conversation.status = "completed"
        db.commit()
        
        # Identify speakers
        speakers = speaker_identifier.identify_speakers(transcript["segments"])
        transcript["speakers"] = speakers
        
        # Analyze turn-taking patterns
        turn_analysis = speaker_identifier.analyze_turn_taking(speakers, transcript["segments"])
        
        # Classify dialogue
        analysis = await classify_dialogue(transcript)
        analysis["turn_taking"] = turn_analysis
        
        # Update conversation
        conversation.transcript = transcript
        conversation.analysis = analysis
        db.commit()
        
    except Exception as e:
        print(f"Error processing conversation {conversation_id}: {str(e)}")
        raise e

@app.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db)
):
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation

@app.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    conversations = db.query(Conversation).offset(skip).limit(limit).all()
    return conversations
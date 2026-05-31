# chatbot_module.py
import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

class GroqAssistant:
    def __init__(self):
        self.api_key = os.getenv("")
        if not self.api_key:
            raise ValueError("Error: GROQ_API_KEY not found in .env file!")
        
        self.client = Groq(api_key=self.api_key)

    def get_answer(self, visual_context, user_question):
        """
        visual_context: A string describing what YOLO sees (e.g., '2 people, 1 laptop')
        user_question: What the user is asking
        """
        system_msg = f"You are an AI security assistant. Currently, the camera sees: {visual_context}."
        
        chat_completion = self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_question},
            ],
            model="llama-3.3-70b-versatile",
        )
        return chat_completion.choices[0].message.content

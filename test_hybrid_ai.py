"""
test_hybrid_ai.py
-----------------
Standalone integration test for Phase 42 Hybrid AI Architecture.
Verifies:
1. Local FinBERT sentiment engine (ProsusAI/finbert)
2. Groq LLM API (llama-3.3-70b-versatile) via LangChain
"""

import asyncio
import os
import time

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from backend.src.services.finbert_analyzer import analyze_news_sentiment

# Load environment variables from .env to get GROQ_API_KEY
load_dotenv()


async def test_finbert():
    print("\n--- 1. Testing Local FinBERT Engine ---")
    print("Note: FinBERT may take a minute to download weights on the very first run.")
    
    headline = "Bitcoin plummets 15% as SEC announces strict new regulations."
    print(f"\nHeadline: '{headline}'")
    
    start_time = time.time()
    result = await analyze_news_sentiment(headline)
    elapsed = time.time() - start_time
    
    print(f"Sentiment:  {result['label'].upper()}")
    print(f"Confidence: {result['score']:.4f}")
    print(f"Local latency: {elapsed:.2f} seconds")


async def test_groq_llm():
    print("\n--- 2. Testing Groq LLM (llama-3.3-70b-versatile) ---")
    
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or not api_key.startswith("gsk_"):
        print("Error: GROQ_API_KEY is missing or invalid in .env")
        return

    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=api_key,
        temperature=0.2,
    )
    
    prompt = "Explain in one sentence why risk management is important in crypto trading."
    print(f"\nPrompt: '{prompt}'")
    
    start_time = time.time()
    try:
        # LangChain Chat models expect a list of messages or a string (which it converts)
        response = await llm.ainvoke(prompt)
        elapsed = time.time() - start_time
        
        print(f"\nResponse: {response.content}")
        print(f"Groq APILatency: {elapsed:.2f} seconds")
    except Exception as e:
        print(f"Groq API Error: {e}")


async def main():
    print("=== Phase 42: Hybrid AI Integration Test ===\n")
    
    await test_finbert()
    await test_groq_llm()
    
    print("\n=== Test Complete ===")


if __name__ == "__main__":
    # Ensure nested asyncio loops (if any) don't crash, though standard run() is fine here
    asyncio.run(main())

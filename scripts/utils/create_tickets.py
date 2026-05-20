import json
import random
import uuid
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI

# Configuration
load_dotenv(override=True)
openai_api_key = os.getenv('OPENAI_API_KEY')

if openai_api_key:
    print(f"OpenAI API Key exists and begins {openai_api_key[:8]}")
else:
    print("OpenAI API Key not set - please head to the troubleshooting guide in the setup folder")

client = OpenAI(api_key=openai_api_key)
MODEL_NAME = "gpt-4o-mini" # Most cost-effective model
TOTAL_TICKETS = 10
BATCH_SIZE = 10
OUTPUT_FILE = "support_tickets.jsonl"

# Constants for random generation
CATEGORIES = ["Software", "Hardware", "Network", "Access Control", "Billing"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]
STATUSES = ["Open", "In Progress", "Resolved", "Closed"]

def generate_random_data():
    """Generates basic ticket data using Python built-in functions."""
    return {
        "ticket_id": f"TIC-{uuid.uuid4().hex[:8].upper()}",
        "created_at": (datetime.now() - timedelta(days=random.randint(0, 30))).isoformat(),
        "category": random.choice(CATEGORIES),
        "priority": random.choice(PRIORITIES),
        "status": random.choice(STATUSES)
    }

def get_llm_content_batch(tickets_data):
    """Calls the LLM to fill text fields for a batch of tickets."""
    
    # Create a prompt that asks for structured data for multiple tickets
    prompt = "Generate realistic support ticket details (customer_name, subject, issue_description, agent_comment) " \
             "for the following ticket categories and priorities. Return ONLY a JSON list of objects.\n\n"
    
    for i, t in enumerate(tickets_data):
        prompt += f"{i+1}. Category: {t['category']}, Priority: {t['priority']}\n"

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that generates synthetic data in JSON format."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        # The LLM returns a JSON string, we parse it
        raw_content = json.loads(response.choices[0].message.content)
        # We expect a list named 'tickets' or similar from the LLM
        return list(raw_content.values())[0] 
    except Exception as e:
        print(f"Error calling LLM: {e}")
        return []

def main():
    all_tickets = []
    
    print(f"Starting generation of {TOTAL_TICKETS} tickets...")

    for i in range(0, TOTAL_TICKETS, BATCH_SIZE):
        # 1. Generate local data for the batch
        batch = [generate_random_data() for _ in range(BATCH_SIZE)]
        
        # 2. Enrich with LLM content
        print(f"Enriching batch {i//BATCH_SIZE + 1} with LLM...")
        llm_details = get_llm_content_batch(batch)
 
        # 3. Merge data
        for j in range(len(batch)):
            if j < len(llm_details):
                batch[j].update(llm_details[j])
            all_tickets.append(batch[j])

    # 4. Save to JSONL
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for ticket in all_tickets:
            f.write(json.dumps(ticket) + '\n')

    print(f"Successfully saved {len(all_tickets)} tickets to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
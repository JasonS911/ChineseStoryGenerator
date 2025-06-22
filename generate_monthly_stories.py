from openai import OpenAI
import os
import json
from datetime import datetime, timedelta, date
# from dotenv import load_dotenv
import calendar

# load_dotenv() 
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# Folder to store generated stories
OUTPUT_DIR = "public/daily_story"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# HSK level by weekday (0 = Monday)
hsk_by_day = {
    0: 1,  # Monday
    1: 2,
    2: 1,
    3: 3,
    4: 4,
    5: 1,
    6: 5   # Sunday
}

def generate_prompt(hsk_level):
    return f"""
Write a short story in simplified Chinese at HSK {hsk_level} level.
Make the story between 4 to 6 sentences. Output a JSON object with three keys:
"chinese" (the original text), "pinyin", and "english" (translation).
"""

def generate_story(date):
    weekday = date.weekday()
    hsk_level = hsk_by_day[weekday]
    prompt = generate_prompt(hsk_level)

    response = client.responses.create(
        model="gpt-3.5-turbo",
        input= prompt,
    )
    
    try:
        story = json.loads(response.output_text)
    except json.JSONDecodeError:
        return

    filename = os.path.join(OUTPUT_DIR, f"{date.strftime('%Y-%m-%d')}.json")
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)


#aautomatically get start date and end date for the month
today = date.today()

# Generate stories for the entire month
start_date = datetime(today.year, today.month, today.day)  # Start from today
end_day = calendar.monthrange(today.year, today.month)[1]  # Get the last day of the month
end_date = datetime(today.year, today.month, end_day)  # Get the last day of the month

# Generate stories for all dates in the range
current_date = start_date
generate_story(current_date)

while current_date <= end_date:
    generate_story(current_date)
    current_date += timedelta(days=1)

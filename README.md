Generate chinese stories using openAI API.

To use generate_monthyl_stories.py example:
python generate_monthly_stories_selenium.py --start-date 2026-01-01 --end-date 2026-12-31 --output-file public/daily_story/stories.json

start date is what day to generate stories from
end date is what day to end story generations
or you can use --days flag for number of days
output file is the path to save files at

To reset session in case message limits are reached: rm -rf path/to/folder/.selenium-chatgpt-profile

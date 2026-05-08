FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY slack_remind.py ./

CMD ["python", "slack_remind.py"]

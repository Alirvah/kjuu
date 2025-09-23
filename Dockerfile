FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PATH="/home/appuser/.local/bin:$PATH"

RUN adduser --disabled-password --uid 1000 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

USER appuser

#CMD ["gunicorn", "myproject.wsgi:application", "--bind", "0.0.0.0:8000"]
CMD ["gunicorn", "kjuu.wsgi:application", "--bind", "0.0.0.0:8000"]


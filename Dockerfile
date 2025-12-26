FROM python:3.12-alpine

WORKDIR /app

ADD requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ADD ecoflow_prometheus.py .
ADD ecoflow/ ./ecoflow/

CMD [ "python", "ecoflow_prometheus.py" ]

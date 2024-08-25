FROM python:3.12-alpine

RUN apk update && apk add py3-pip

ADD requirements.txt /requirements.txt
RUN pip install -r /requirements.txt

ADD ecoflow_prometheus.py /ecoflow_prometheus.py

CMD [ "python", "/ecoflow_prometheus.py" ]

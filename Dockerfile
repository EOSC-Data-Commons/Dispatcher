FROM python:3.13  

RUN groupadd -r celery && useradd -r -g celery celery
WORKDIR /usr/src
 
# Set environment variables 
# Prevents Python from writing pyc files to disk
ENV PYTHONDONTWRITEBYTECODE=1
#Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1 
 
# Upgrade pip
RUN pip install --upgrade pip 
 
# Copy the Django project  and install dependencies
COPY requirements.txt /usr/src

# run this command to install all dependencies 
RUN pip install --no-cache-dir -r requirements.txt

COPY . /usr/src

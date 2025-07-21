FROM python:3.13  

WORKDIR /usr/src
 
# Set environment variables 
# Prevents Python from writing pyc files to disk
ENV PYTHONDONTWRITEBYTECODE=1
#Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1 
 
# Upgrade pip
RUN pip install --upgrade pip 
 
# Copy the Django project  and install dependencies
COPY ./requirements.txt /usr/src

# run this command to install all dependencies 
RUN pip install --no-cache-dir -r requirements.txt
COPY . /usr/src
#COPY ./devel-conf.yaml /usr/src/devel-conf.yaml
RUN jinja2 /usr/src/nginx/conf/nginx.conf.j2 /usr/src/devel-conf.yaml >  /usr/src/nginx/conf/nginx.conf
FROM nginxinc/nginx-unprivileged:latest
WORKDIR /usr/src
COPY --from=0  /usr/src/nginx/conf/nginx.conf /etc/nginx/nginx.conf 

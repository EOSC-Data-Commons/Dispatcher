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
COPY requirements.txt  /app/
COPY . /usr/src

# run this command to install all dependencies 
RUN pip install --no-cache-dir -r requirements.txt
 
# Copy the Django project to the container
 
# # Expose the Django port
# EXPOSE 8000
# #CMD ["ls", "app"]
# CMD ["fastapi", "run", "app/main.py", "--port", "8000"]
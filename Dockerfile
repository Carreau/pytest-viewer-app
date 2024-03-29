FROM python:3.10.9-alpine
WORKDIR /code
RUN apk add --no-cache gcc musl-dev linux-headers
RUN apk add --no-cache libffi-dev
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
EXPOSE 1234
COPY . .
CMD ["python", "-m", "src","serve"]

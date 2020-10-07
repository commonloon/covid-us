# covid-us
Flask app to plot covid new case data for all US states

I created this app as an exercise to help me learn to use the d3 javascript library.

As a follow-on, I modified it to deploy to AWS Lambda to avoid paying for an EC2 instance to run it.
I use the "serverless" framework to deploy the app, following the tutorial at https://www.serverless.com/blog/flask-python-rest-api-serverless-lambda-dynamodb

This is my first Lambda app, so I've probably done some stuff non-optimally.
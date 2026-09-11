# AWS runtime source

This folder contains only the application files used by the deployed AWS
prototype. It deliberately excludes deployment scripts, smoke tests, local
unit tests, stage packages, CloudFormation, IAM policies, and data-upload code.

## Included application components

- `Lambda/` contains the Python inference handler, predictor, frozen model,
  threshold table, pinned runtime dependencies, and Docker definition used to
  build the Lambda container image.
- `S3_Frontend/` contains the HTML, CSS, and JavaScript files currently served
  from S3 through CloudFront.

There are no source folders for DynamoDB, ECR, API Gateway, IAM, CloudWatch, or
CloudFront. Those services store data, images, permissions, logs, routes, or
delivery configuration. They do not run additional project source code.

The frontend `config.js` records the API endpoint used by the deployed site at
the time this snapshot was created. If the API is recreated with a different
URL, update that one value before uploading the frontend again.

The DynamoDB demo records are not included because they are application data,
not source code. The original deidentified `demo_patients.json` should remain
with the protected project artifacts rather than this source-only folder.

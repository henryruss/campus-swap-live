# Carousel Images on AWS (S3 + CloudFront)

To make carousel images load faster, host them on AWS S3 with CloudFront. Once set up, set the `CAROUSEL_CDN_URL` environment variable and images will load from the CDN instead of your app server.

## Setup Steps

1. **Create an S3 bucket** (e.g. `campusswap-carousel`). Enable public access if you want public URLs, or use a CloudFront Origin Access Control (recommended).

2. **Upload the images** from `static/CarouselPics/` to the bucket. Keep the folder structure:
   - `CarouselPics/couch.png`
   - `CarouselPics/futon.png`
   - etc.

3. **Create a CloudFront distribution**:
   - Origin: your S3 bucket
   - Enable "Origin Access Control" (OAC) if the bucket is private
   - No need to restrict to a path

4. **Set the environment variable** on your host (Render, etc.):
   ```
   CAROUSEL_CDN_URL=https://d1234abcd.cloudfront.net
   ```
   Use your CloudFront distribution URL (no trailing slash).

5. **Deploy** – carousel images will now load from CloudFront edge locations worldwide.

## Without CloudFront

You can also use the S3 bucket URL directly (slower, no edge caching):
```
CAROUSEL_CDN_URL=https://your-bucket.s3.us-east-1.amazonaws.com
```

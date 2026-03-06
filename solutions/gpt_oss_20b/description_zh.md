# GPT OSS 20B Jetson Solution

This solution deploys a prebuilt GPT OSS 20B container to an NVIDIA Jetson device over SSH.

After deployment, the container starts `llama-server` and exposes an HTTP service on port `8080`.

You can then open the service directly in a browser:

`http://<jetson-ip>:8080`

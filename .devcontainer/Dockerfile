FROM debian:bookworm-slim

# Install base tools and Python 3.11
RUN apt update && apt install -y \
    bash \
    git \
    curl \
    python3.11 \
    python3.11-distutils \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Create a symlink for python3 to point to python3.11
RUN ln -sf /usr/bin/python3.11 /usr/bin/python3

WORKDIR /workspace

# Install requirements
COPY requirements.txt .
RUN python3.11 -m pip install --no-cache-dir -r requirements.txt

CMD ["/bin/bash"]
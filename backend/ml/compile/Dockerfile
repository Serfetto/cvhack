FROM python:3.12.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLCONFIGDIR=/tmp/matplotlib

# Build with the unzipped official LinQ SDK directory as the Docker context:
# docker build -f backend/ml/compile/Dockerfile -t cvhack-linq /path/to/tpu_framework
COPY packets/ /opt/linq/packets/

# The CPU PyTorch wheels satisfy the SDK's exact torch/torchvision versions
# without bringing CUDA libraries into this compiler image.
RUN python -m pip install --upgrade pip \
 && python -m pip install --index-url https://download.pytorch.org/whl/cpu \
      'torch==2.9.1+cpu' 'torchvision==0.24.1+cpu'
RUN cd /opt/linq/packets && python -m pip install -r requirements.txt
RUN python -m pip install 'numpy==1.26.4' 'opencv-python-headless==4.11.0.86' \
      'matplotlib<3.11' 'pandas<3' 'seaborn<0.14' psutil py-cpuinfo ultralytics-thop onnxslim \
 && python -m pip install --no-deps 'ultralytics==8.4.0'

WORKDIR /work

FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV ANDROID_HOME=/opt/android
ENV PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/build-tools/34.0.0:/usr/local/bin
ENV _JAVA_OPTIONS="-Xmx256m"

RUN apt-get update && apt-get install -y \
    openjdk-17-jdk-headless \
    clang \
    llvm \
    mingw-w64 \
    wget \
    unzip \
    zip \
    zipalign \
    apksigner \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p $ANDROID_HOME/cmdline-tools && \
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-10406996_latest.zip -O cmdline-tools.zip && \
    unzip -q cmdline-tools.zip -d $ANDROID_HOME/cmdline-tools && \
    rm cmdline-tools.zip && \
    mv $ANDROID_HOME/cmdline-tools/cmdline-tools $ANDROID_HOME/cmdline-tools/latest && \
    yes | sdkmanager --licenses && \
    sdkmanager "build-tools;34.0.0" "platforms;android-35"

RUN wget -q https://github.com/google/bundletool/releases/download/1.15.6/bundletool-all-1.15.6.jar -O /opt/bundletool.jar && \
    echo '#!/bin/bash\njava -jar /opt/bundletool.jar "$@"' > /usr/local/bin/bundletool && \
    chmod +x /usr/local/bin/bundletool

RUN wget -q https://github.com/indygreg/apple-platform-rs/releases/download/apple-codesign%2F0.22.0/apple-codesign-0.22.0-x86_64-unknown-linux-musl.tar.gz -O rcodesign.tar.gz && \
    tar -xzf rcodesign.tar.gz && \
    mv apple-codesign-*-unknown-linux-musl/rcodesign /usr/local/bin/ && \
    rm -rf apple-codesign-* rcodesign.tar.gz

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 5000

CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-5000}"
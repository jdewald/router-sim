#!/usr/bin/env bash
# Install PlantUML
set -e

# taken from https://github.com/metanorma/plantuml-install/blob/master/centos.sh
PLANTUML_URL="${PLANTUML_URL:-http://sourceforge.net/projects/plantuml/files/plantuml.jar/download}"

if [ -f "/opt/plantuml/plantuml.jar" ]; then
  echo '[plantuml] PlantUML already installed.'
else
  echo '[plantuml] Installing PlantUML...'
  yum install -y java-1.8.0-openjdk graphviz
  mkdir -p /opt/plantuml && \
    curl -o /opt/plantuml/plantuml.jar \
    -L "${PLANTUML_URL}"
  printf '#!/bin/sh\nexec java -jar /opt/plantuml/plantuml.jar "$@"' > /usr/bin/plantuml
  chmod +x /usr/bin/plantuml
fi
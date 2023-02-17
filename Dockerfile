FROM jupyter/base-notebook:python-3.10.9

USER root
ENV PLANTUML_URL="http://sourceforge.net/projects/plantuml/files/plantuml.jar/download"
RUN apt-get update && apt-get install -y curl openjdk-8-jre libffi-dev graphviz
RUN mkdir -p /opt/plantuml && \
    curl -o /opt/plantuml/plantuml.jar \
    -L "${PLANTUML_URL}" && \
  printf '#!/bin/sh\nexec java -Djava.awt.headless=true -jar /opt/plantuml/plantuml.jar "$@"' > /usr/bin/plantuml && \
  chmod +x /usr/bin/plantuml

RUN mkdir -p /opt/app
COPY routersim /opt/app/routersim
COPY plantuml.py /opt/app
COPY simhelpers.py /opt/app
COPY setup.py /opt/app
WORKDIR /opt/app
RUN python3 setup.py install 

# restore back to the jupyter base. Might get rid of this?
USER ${NB_UID}
WORKDIR "${HOME}"

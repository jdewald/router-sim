FROM centos:centos7

LABEL maintainer="joshua.dewald@stackpath.com"

ENV PYTHON_VERSION=3.9.4

# Install all requirements gotten through yum package manager
RUN yum -y update \
    && yum -y install net-tools iproute telnet bind-utils make wget git which vim \
                      gcc gcc-c++ openssl-devel bzip2-devel cyrus-sasl-devel \
                      cyrus-sasl-plain cyrus-sasl-gs2 cyrus-sasl-gssapi cyrus-sasl-sql \
                      python35-devel python35-lxml sqlite-devel curl automake autoconf \
                      libtool make six unzip zlib-devel \
 	&& yum clean all \
	&& rm -rf /var/cache/yum

RUN yum -y install libffi-devel java-1.8.0-openjdk graphviz

ENV PLANTUML_URL="http://sourceforge.net/projects/plantuml/files/plantuml.jar/download"
RUN mkdir -p /opt/plantuml && \
    curl -o /opt/plantuml/plantuml.jar \
    -L "${PLANTUML_URL}" && \
  printf '#!/bin/sh\nexec java -Djava.awt.headless=true -jar /opt/plantuml/plantuml.jar "$@"' > /usr/bin/plantuml && \
  chmod +x /usr/bin/plantuml

WORKDIR /tmp

# Install Python
RUN wget http://python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tar.xz \
    && tar xf Python-${PYTHON_VERSION}.tar.xz \
    && cd Python-${PYTHON_VERSION} \
    && ./configure\
    && make \
    && make install \
    && rm -rf /tmp/Python-${PYTHON_VERSION}

# Create symbolic link from /usr/bin/python3 to /usr/local/bin/python3
# - - -
# Bazel hard-codes a path to /usr/bin/python3 in generated Python entrypoint
# This makes sure that path leads to the Python version installed here
RUN ln -s /usr/local/bin/python3.9 /usr/bin/python3

# Upgrade pip, install requirements
RUN pip3.9 install --upgrade pip && \
    pip3.9 install jupyter \
                   widgetsnbextension \
                   ipyleaflet \
                   seaborn \
                   psutil \
                   tableauhyperapi

RUN python3.9 -m jupyter nbextension install --py widgetsnbextension
RUN python3.9 -m jupyter nbextension enable --py widgetsnbextension
RUN python3.9 -m jupyter nbextension install --py --symlink --sys-prefix ipyleaflet
RUN python3.9 -m jupyter nbextension enable --py --sys-prefix ipyleaflet

WORKDIR /notebooks
RUN mkdir -p /notebooks/my_notebooks
VOLUME /notebooks/my_notebooks

RUN mkdir -p /opt/app
COPY routersim /opt/app/routersim
COPY plantuml.py /opt/app
COPY simhelpers.py /opt/app
COPY setup.py /opt/app
WORKDIR /opt/app
RUN python3.9 setup.py install 

COPY launch_notebook.py /opt
WORKDIR /notebooks


# Amongst other things, override display url so user can actually cmd+click on it to go to notebooks
CMD ["notebook", "--allow-root", "--no-browser", "--ip", "0.0.0.0", "--NotebookApp.custom_display_url=http://localhost:8888"]
ENTRYPOINT ["python3.9", "/opt/launch_notebook.py"]

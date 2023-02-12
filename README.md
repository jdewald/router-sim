# routersim

## What the heck is this?

This repository contains a toy implementation of router technologies intended for exploration and learning. 
Specifically, it will implement various routing protocols (IS-IS, OSPF, BGP, static) as well as performing routing (forwarding) of packets based on teh derived tables.

In terms of router implementation the following is there:
* Packet forwarding
* Distinct route tables (that feed forwarding tables)
* IS-IS routing protocol for learning routes
* RSVP-TE with Facility protection 
* Forwarding via MPLS of "BGP-learned" routes
* PING/ICMP 

A work-in-progress branch has added:
* Layer 2 support
* Switching
* ARP

Additionally there is WIP for:
* RSTP (sort of a requirement to do Layer2 with arbitrary topologies)

The tooling around it can generate:
* Sequence diagrams
* Topology diagrams

The key aspect of the functionality is that it operates in discrete time units and generates events which can be used to create various interaction diagrams (Sequence, Activity, Timing, etc). 

Additionally, to aid in the exploration there are convenience classes and methods for quickly spinning up a topology.

At the time of this writing, there are no external dependencies on the Python side (it is written for Python3). To view the generated PlantUML diagrams it is helpful to have a `plantuml` binary in the path, but they can also be viewed in VSCode.

## Jupyter notebook

As a mechanism to provide an all-in-one and convenient method to run and view the simulation, this repository also contains a `Dockerfile` which will generate a container image which has Jupyter notebook, the routersim, and various binaries (such as `plantuml`). 

You can see an example of what the [notebook can do here](samples/isis_demo/isis_demo.md).
### QuickStart

A container has been pre-built and available to just download and run if you don't want to build locally

Create a directory which will hold your notebooks. Note that this is the same base path you may be using for the existing data-eng Needle notebook

`mkdir -p $HOME/needle_notebooks/routersim`

Grab the image

`docker pull jdewald/routersim-notebook:latest`

Run the image, mounting the directory to /notebooks/my_notebooks which the container is aware of. You can use any local port, but 8888 will be the container port

`sudo docker run --rm -p 8888:8888 -v $HOME/needle_notebooks:/notebooks/my_notebooks routersim-notebook:latest`

You will see a path in the output, you can visit that (e.g http://localhost:8888/?token=...)

Ideally you will see some notebooks in the `demos` folder, but if not you can grab some from me.


## Internals

### Events



from collections import OrderedDict
from abc import ABC, abstractmethod
import subprocess


class Actor:
    def __init__(self, sequence, name, type='actor'):
        self.diagram = sequence
        self.name = name
        self.type = type
        self.mappings = {}

    def send_message(self, target, msg, note=None):
        self.diagram.send_message(
            self.name, target_name=target.name, msg=msg, note=note)

    def add_mapping(self, key, value):
        self.mappings[key] = value


class Diagram(ABC):
    def __init__(self, title):
        self.title = title
        self.groups = OrderedDict()
        self.actors = {}
        self.messages = []

    def group(self, group_name):
        if group_name not in self.groups:
            self.groups[group_name] = {
                'name': group_name,
                'entities': []
            }
        return self.groups[group_name]

    def actor(self, actor_name, type='actor', group='default'):
        if actor_name not in self.actors:
            self.actors[actor_name] = Actor(self, actor_name, type)

            g = self.group(group)
            g['entities'].append(self.actors[actor_name])

        return self.actors[actor_name]

    def send_message(self, source_name=None, target_name=None, msg=None, note=None):
        self.messages.append((source_name, target_name, msg, note))

    def clear_messages(self):
        self.messages.clear()

    def png(self):
        data = self.render_syntax()

        # pipe will make it read/write stdin/stdout
        proc = subprocess.Popen('plantuml -pipe',
                                shell=True,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE)

        out = proc.communicate(data.encode())[0]
        return out

    @abstractmethod
    def render_syntax(self):
        pass


class Sequence(Diagram):

    def __init__(self, title):
        super().__init__(title)
        self.autonumber = True

    def render_syntax(self):
        output = ""

        output += "@startuml\n"

        output += f"title {self.title}\n\n"

        if self.autonumber:
            output += "autonumber\r\n"

        output += "\n\n"

        for group_name in self.groups:
            if group_name != 'default':
                output += f"box {group_name}\n"

                for actor in self.groups[group_name]['entities']:
                    output += f"\t{actor.type} {actor.name}\n"

            if group_name != 'default':
                output += "end box\n"

        for message in self.messages:
            output += f"{message[0]}-->{message[1]}: {message[2]}\n"

            if message[3] is not None:
                output += f"note over {message[0]}\n{message[3]}\nend note\n"

            output += "\n"

        output += "\n\n"
        output += "@enduml\n"

        return output


class ObjectDiagram(Diagram):

    def render_syntax(self):
        output = ""

        output += "@startuml\n"

        output += f"title {self.title}\n\n"

        output += "\n\n"

        for group_name in self.groups:
            if group_name != 'default':
                output += f"""package "{group_name}" {{\n"""
            # TODO: box supported on object?
            for actor in self.groups[group_name]['entities']:
                if actor.type == 'map':
                    output += f"map {actor.name} {{\n"
                    for key in actor.mappings:
                        output += f"\t{key} => {actor.mappings[key]}\n"
                    output += "}\n"
                    output += "\n\n"
            if group_name != 'default':
                output += "}\n"

        for message in self.messages:
            output += f"{message[0]}-->{message[1]}\n"

            if message[3] is not None:
                output += f"note over {message[0]}\n{message[3]}\nend note\n"

            output += "\n"

        output += "\n\n"
        output += "@enduml\n"

        return output


class ComponentDiagram(Diagram):

    def group(self, name, type='package'):
        group = super().group(name)
        group['type'] = type
        return group

    def render_syntax(self):
        output = ""

        output += "@startuml\n"

        output += f"title {self.title}\n\n"

        output += "\n\n"

        for group_name in self.groups:
            # TODO: box supported on object?
            group = self.groups[group_name]

            if group_name != "default":
                output += f"""{group['type']} "{group_name}" {{\n"""
            for actor in self.groups[group_name]['entities']:
                output += f"\t[{actor.name}]\n"
            if group_name != "default":
                output += "}\n"

        for message in self.messages:
            output += f"[{message[0]}] - [{message[1]}]\n"

#            if message[3] is not None:
#                output += f"note  {message[0]}\n{message[3]}\nend note\n"

            output += "\n"

        output += "\n\n"
        output += "@enduml\n"

        return output

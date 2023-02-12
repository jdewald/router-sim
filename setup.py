from distutils.core import setup
setup(name='routersim',
      version='0.1',
      packages=[
        'routersim',
        'routersim.isis',
        'routersim.rsvp',
        ],
      py_modules=[
        'plantuml',
        'simhelpers',
      ],
      )

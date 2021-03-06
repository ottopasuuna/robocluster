from setuptools import setup

setup(name='robocluster',
      version='0.1',
      description='Distributed robotics framework',
      url='https://github.com/UofSSpaceTeam/robocluster',
      author='UofSSpaceTeam',
      author_email='software@usst.ca',
      license='ECL-2.0',
      packages=['robocluster'],
      install_requires=[
            'pyserial-asyncio',
            'pyvesc'
      ],
      dependency_links=[
            'https://github.com/UofSSpaceTeam/PyVESC.git'
      ],
      zip_safe=False,
)


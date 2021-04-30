import os
from codecs import open
from setuptools import find_packages, setup
from subprocess import check_output

# -----------------------------------------------------------------------------
# Version handler


command = 'git describe --tags --long --dirty --always'
fmt = '{tag}.dev{commitcount}+{gitsha}'


def format_version(version, fmt=fmt):
    parts = version.split('-')

    # This is an unknown fork/branch being run in the CI
    if len(parts) == 1:
        return fmt.format(tag='ci', commitcount=0, gitsha=version)

    # Sometimes the closest tag has '-dev' and messes everything up
    if len(parts) == 5 and parts[1] == 'dev':
        parts = [parts[0] + '-dev', parts[2], parts[3], parts[4]]

    assert len(parts) in (3, 4), '|'.join(parts)
    dirty = len(parts) == 4
    tag, count, sha = parts[:3]
    if count == '0' and not dirty:
        return tag
    return fmt.format(tag=tag, commitcount=count, gitsha=sha.lstrip('g'))


def get_git_version():
    git_version = check_output(command.split()).decode('utf-8').strip()
    return format_version(version=git_version)

# -----------------------------------------------------------------------------
# Readme Importer


here = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()


install_requires = [
    'Django>=1.11,<3.2',
    'djangorestframework>=3.9.1,<4.0',
    'django-rest-swagger>=2.2.0',
    'requests>=2.18,<3',
    'elasticsearch7>=7.0.0,<8.0.0',
    'django-localflavor>=1.1,<3.1',
    'django-flags>=4.0.1,<5.1',
    'requests-aws4auth'
]

testing_extras = [
    'coverage>=4.5.1,<5',
    'mock==2.0.0',
    'deep==0.10',
    'deepdiff>=3.3,<5.0',
    'django-nose==1.4.1',
    'parameterized==0.6.1',
    'elasticsearch7>=7.0.0,<8.0.0',
    'requests-aws4auth'
]

docs_extras = [
    'mkdocs==0.17.5',
    'mkDOCter==1.0.5',
]


setup(
    name='ccdb5-api',
    version=get_git_version(),
    description='Complaint Search API',
    long_description=long_description,
    url='https://github.com/cfpb/ccdb5-api',
    author='CFPB',
    author_email='tech@cfpb.gov',
    license='CC0',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'Topic :: Internet :: WWW/HTTP :: Indexing/Search',
        'License :: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Framework :: Django',
    ],
    keywords='complaint search api',
    packages=find_packages(exclude=['contrib', 'docs', 'tests']),
    setup_requires=[],
    install_requires=install_requires,
    extras_require={
        'docs': docs_extras,
        'testing': testing_extras,
    }
)

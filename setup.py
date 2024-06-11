from setuptools import setup, find_packages

setup(
    name='astound',
    version='0.1.0',
    author='Holly Mandel',
    author_email='hollym92@gmail.com',
    description='llm-powered script explainer',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/hollymandel/ASTound',
    packages=find_packages(),
    install_requires=[
        'anthropic',
        'ast',
        'astor',
        'json'
    ],
    python_requires='>=3.6',
    include_package_data=True,
    package_data={
        'sample': ['data/*.json'],
    }
)

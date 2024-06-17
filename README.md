`Astound` is a code explainer powered by Claude. Create a root node based on a source file and then build a tree by navigating the abstract syntax tree (`ast`) of this source. If you encounter a reference outside this source, create a new node based on a different source, attach it as a child, and then continue navigating. Once you have attached all the nodes you want explained, navigate up to the top of the tree and call `summarize_down` to obtain a recursive summary of the current node and its children.

You will need to enter your own Anthropic API key. This can be done via the environment variable `ANTHROPIC_API_KEY` or by editing `astound/config.json`. The config file also determines the Claude version. This [quickstart guide](https://docs.anthropic.com/en/docs/quickstart-guide) from Anthropic may be helpful.

The main value-add of `astound` is that it provides a convenient way to select and concatenate the bits of code to submit to the language model. This tells Claude what parts of the code you want to focus on. I'm less sure whether recursive summarization provides an additional advantage for frontier models.

Want to know how `astound` works?  `Astound` can help! [See the demo](https://github.com/hollymandel/astound/blob/main/demo.ipynb).

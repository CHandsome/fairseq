import torch
import torch.nn as nn

from fairseq.tasks.language_modeling import LanguageModelingTask
from fairseq.modules import (
    ElmoTokenEmbedder, MultiheadAttention,
    CharacterTokenEmbedder)
from . import (
    BaseFairseqModel, register_model, register_model_architecture,
)

from fairseq import options
from fairseq import utils


@register_model('finetuning_squad')
class FinetuningSquad(BaseFairseqModel):
    def __init__(self, args, language_model, eos_idx, pad_idx, unk_idx):
        super().__init__()

        self.language_model = language_model
        self.eos_idx = eos_idx
        self.pad_idx = pad_idx
        self.unk_idx = unk_idx

        self.last_dropout = nn.Dropout(args.last_dropout)
        self.start_proj = torch.nn.Linear(args.model_dim, 2, bias=True)
        self.end_proj = torch.nn.Linear(args.model_dim, 2, bias=True)
        self.imp_proj = torch.nn.Linear(args.model_dim * 3, 2, bias=True)

        if isinstance(self.language_model.decoder.embed_tokens, CharacterTokenEmbedder):
            print('disabling training char convolutions')
            self.language_model.decoder.embed_tokens.disable_convolutional_grads()

        self.reset_parameters()

    def reset_parameters(self):
        torch.nn.init.constant_(self.start_proj.weight, 0)
        torch.nn.init.constant_(self.start_proj.bias, 0)

        torch.nn.init.constant_(self.end_proj.weight, 0)
        torch.nn.init.constant_(self.end_proj.bias, 0)

        torch.nn.init.constant_(self.imp_proj.weight, 0)
        torch.nn.init.constant_(self.imp_proj.bias, 0)

    def forward(self, text):
        x, _ = self.language_model(text)
        if isinstance(x, list):
            x = x[0]

        idxs = text.eq(self.eos_idx)

        x = self.last_dropout(x)

        eos_emb = x[idxs].view(text.size(0), 1, -1)  # assume only 3 eoses per sample

        imp = self.imp_proj(eos_emb).squeeze(-1)
        start = self.start_proj(x)
        end = self.end_proj(x)

        return imp, start, end

    @staticmethod
    def add_args(parser):
        """Add model-specific arguments to the parser."""
        parser.add_argument('--lm-path', metavar='PATH', help='path to elmo model')
        parser.add_argument('--model-dim', type=int, metavar='N', help='decoder input dimension')
        parser.add_argument('--last-dropout', type=float, metavar='D', help='dropout before projection')
        parser.add_argument('--model-dropout', type=float, metavar='D', help='lm dropout')
        parser.add_argument('--attention-dropout', type=float, metavar='D', help='lm dropout')
        parser.add_argument('--relu-dropout', type=float, metavar='D', help='lm dropout')

    @classmethod
    def build_model(cls, args, task):
        """Build a new model instance."""

        # make sure all arguments are present in older models
        base_architecture(args)

        dictionary = task.dictionary

        assert args.lm_path is not None

        task = LanguageModelingTask(args, dictionary, dictionary)
        models, _ = utils.load_ensemble_for_inference([args.lm_path], task, {
            'remove_head': True,
            'dropout': args.model_dropout,
            'attention_dropout': args.attention_dropout,
            'relu_dropout': args.relu_dropout,
        })
        assert len(models) == 1, 'ensembles are currently not supported for elmo embeddings'

        return FinetuningSquad(args, models[0], dictionary.eos(), dictionary.pad(), dictionary.unk())


@register_model_architecture('finetuning_squad', 'finetuning_squad')
def base_architecture(args):
    args.model_dim = getattr(args, 'model_dim', 1024)
    args.last_dropout = getattr(args, 'last_dropout', 0.1)
    args.model_dropout = getattr(args, 'model_dropout', 0.1)
    args.attention_dropout = getattr(args, 'attention_dropout', 0.1)
    args.relu_dropout = getattr(args, 'relu_dropout', 0.05)
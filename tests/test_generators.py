"""Generators, field parsing and naming."""

from __future__ import annotations

import ast

import pytest

from sillo_start.exceptions import GeneratorError
from sillo_start.generators.model import FIELD_TYPES, ModelGenerator, parse_fields
from sillo_start.generators.registry import registry
from sillo_start.utils import naming


class TestFieldParsing:
    def test_parses_a_simple_field(self):
        (field,) = parse_fields(["title:str"])
        assert field.name == "title"
        assert field.kind == "str"

    def test_parses_flags(self):
        (field,) = parse_fields(["email:str:unique:index"])
        assert field.unique is True
        assert field.indexed is True

    def test_parses_a_default(self):
        (field,) = parse_fields(["views:int:default=0"])
        assert field.default == "0"
        assert "default=0" in field.render()

    def test_parses_a_max_length(self):
        (field,) = parse_fields(["code:str:max=10"])
        assert "max_length=10" in field.render()

    def test_normalises_the_field_name(self):
        (field,) = parse_fields(["publishedAt:datetime"])
        assert field.name == "published_at"

    def test_a_relationship_takes_its_target(self):
        (field,) = parse_fields(["author:fk:User"])
        assert field.target == "User"
        assert "ForeignKeyField" in field.render()
        assert "models.User" in field.render()

    def test_the_reverse_accessor_is_named_for_the_owning_model(self):
        """Post.author -> User should give user.posts, not user.authors."""
        (field,) = parse_fields(["author:fk:User"], owner="Post")
        assert "related_name='posts'" in field.render()

    def test_a_relationship_without_a_target_is_rejected(self):
        with pytest.raises(GeneratorError) as error:
            parse_fields(["author:fk"])[0].render()
        assert "needs a target" in str(error.value)

    def test_an_unknown_type_lists_the_valid_ones(self):
        with pytest.raises(GeneratorError) as error:
            parse_fields(["title:nonsense"])
        assert "Valid types" in str(error.value.hint)

    def test_an_unknown_flag_lists_the_valid_ones(self):
        with pytest.raises(GeneratorError) as error:
            parse_fields(["title:str:nonsense"])
        assert "Valid flags" in str(error.value.hint)

    def test_a_malformed_declaration_is_rejected(self):
        with pytest.raises(GeneratorError):
            parse_fields(["justaname"])

    @pytest.mark.parametrize("kind", sorted(FIELD_TYPES))
    def test_every_declared_type_renders_valid_python(self, kind):
        (field,) = parse_fields([f"value:{kind}"])
        ast.parse(field.render())

    def test_nullable_fields_get_an_optional_annotation(self):
        (field,) = parse_fields(["body:text:null"])
        assert field.python_type == "str | None"


class TestGeneratorRegistry:
    def test_the_expected_generators_are_registered(self):
        for name in ("model", "controller", "service", "repository", "job", "policy"):
            assert registry.has(name)

    def test_an_unknown_generator_lists_the_valid_ones(self):
        with pytest.raises(GeneratorError) as error:
            registry.get("nonsense")
        assert "Available" in str(error.value.hint)

    def test_a_suffix_is_appended_only_once(self):
        generator = registry.get("controller")
        assert generator.normalise("User") == "UserController"
        assert generator.normalise("UserController") == "UserController"

    def test_names_are_converted_to_pascal_case(self):
        assert registry.get("service").normalise("billing_engine") == "BillingEngineService"

    def test_an_unusable_name_is_rejected(self):
        with pytest.raises(GeneratorError):
            registry.get("service").normalise("123")

    def test_requirements_are_enforced(self, manifest):
        with pytest.raises(GeneratorError) as error:
            registry.get("model").check_requirements(manifest)
        assert "uses_record" in str(error.value)

    def test_requirements_pass_when_the_feature_is_enabled(self, fullstack_manifest):
        registry.get("model").check_requirements(fullstack_manifest)  # must not raise


class TestModelGeneration:
    def test_produces_valid_python(self, fullstack_manifest):
        operations = ModelGenerator().plan(
            "Post", fullstack_manifest, fields=["title:str", "body:text:null"]
        )
        create = operations[0]
        ast.parse(create.content)

    def test_the_table_name_is_pluralised(self, fullstack_manifest):
        operations = ModelGenerator().plan("BlogPost", fullstack_manifest, fields=["title:str"])
        assert 'table = "blog_posts"' in operations[0].content

    def test_companions_are_opt_in(self, fullstack_manifest):
        without = ModelGenerator().plan(
            "Post", fullstack_manifest, fields=["title:str"], schema=False, tests=False
        )
        with_extras = ModelGenerator().plan(
            "Post", fullstack_manifest, fields=["title:str"], repository=True, controller=True
        )
        assert len(with_extras) > len(without)

    def test_timestamps_can_be_disabled(self, fullstack_manifest):
        operations = ModelGenerator().plan(
            "Post", fullstack_manifest, fields=["title:str"], timestamps=False
        )
        assert "TimestampsMixin" not in operations[0].content


class TestNaming:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("BlogPost", "blog_post"), ("blogPost", "blog_post"), ("blog-post", "blog_post"),
         ("APIKey", "api_key"), ("blog post", "blog_post")],
    )
    def test_snake_case(self, value, expected):
        assert naming.to_snake(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("blog_post", "BlogPost"), ("blog-post", "BlogPost"), ("api_key", "ApiKey")],
    )
    def test_pascal_case(self, value, expected):
        assert naming.to_pascal(value) == expected

    @pytest.mark.parametrize(
        ("word", "expected"),
        [("post", "posts"), ("category", "categories"), ("box", "boxes"),
         ("person", "people"), ("child", "children"), ("data", "data"), ("day", "days")],
    )
    def test_pluralisation(self, word, expected):
        assert naming.pluralize(word) == expected

    def test_table_names_pluralise_only_the_last_word(self):
        assert naming.table_name("BlogPost") == "blog_posts"
        assert naming.table_name("UserCategory") == "user_categories"

    @pytest.mark.parametrize("name", ["my-app", "my_app", "App2", "a"])
    def test_valid_project_names(self, name):
        assert naming.is_valid_project_name(name)

    @pytest.mark.parametrize("name", ["", "1app", "my app", "class", "-x", "a" * 200])
    def test_invalid_project_names(self, name):
        assert not naming.is_valid_project_name(name)

    def test_package_names_are_importable(self):
        assert naming.package_name_for("my-cool.app") == "my_cool_app"

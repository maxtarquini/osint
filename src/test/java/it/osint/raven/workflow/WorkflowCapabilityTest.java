package it.osint.raven.workflow;

import it.osint.raven.dto.article.EntityDto;
import it.osint.raven.dto.article.MetadataDto;
import org.junit.jupiter.api.Test;

import java.lang.module.ModuleDescriptor.Version;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class WorkflowCapabilityTest {

    @Test
    void equalityUsesNamespaceIdAndVersionOnly() {
        Version version = Version.parse("2.0.0");
        WorkflowCapability first = WorkflowCapability.builder()
                .namespace("osint")
                .id("entity-extraction")
                .description("Extracted entities")
                .type(List.class)
                .version(version)
                .required(true)
                .aliases(Set.of("entities", "ner"))
                .build();
        WorkflowCapability second = WorkflowCapability.builder()
                .namespace("osint")
                .id("entity-extraction")
                .description("Different description")
                .type(EntityDto.class)
                .version(version)
                .required(false)
                .aliases(Set.of("other"))
                .build();
        WorkflowCapability differentNamespace = WorkflowCapability.builder()
                .namespace("graph")
                .id("entity-extraction")
                .type(List.class)
                .version(version)
                .build();

        assertEquals(first, second);
        assertEquals(first.hashCode(), second.hashCode());
        assertNotEquals(first, differentNamespace);
    }

    @Test
    void exposesQualifiedNameAndAliasMatching() {
        WorkflowCapability capability = WorkflowCapability.builder()
                .namespace("nlp")
                .id("entity-extraction")
                .description("Named entity extraction output")
                .type(List.class)
                .version(Version.parse("1.2.0"))
                .aliases(Set.of("entities", "ner"))
                .build();

        assertEquals("nlp:entity-extraction@1.2.0", capability.qualifiedName());
        assertTrue(capability.supportsAlias("entities"));
        assertTrue(capability.matches("nlp", "ner", Version.parse("1.2.0")));
        assertFalse(capability.matches("nlp", "ner", Version.parse("2.0.0")));
        assertFalse(capability.matches("graph", "ner", Version.parse("1.2.0")));
    }

    @Test
    void matchesOtherCapabilityUsingAliasesButNotJavaType() {
        WorkflowCapability canonical = WorkflowCapability.builder()
                .namespace("osint")
                .id("entity-extraction")
                .type(List.class)
                .aliases(Set.of("entities"))
                .build();
        WorkflowCapability alias = WorkflowCapability.builder()
                .namespace("osint")
                .id("entities")
                .type(MetadataDto.class)
                .build();

        assertTrue(canonical.matches(alias));
        assertNotEquals(canonical, alias);
    }

    @Test
    void normalizesOptionalFieldsAndKeepsAliasesImmutable() {
        WorkflowCapability capability = WorkflowCapability.builder()
                .id(" metadata ")
                .type(MetadataDto.class)
                .aliases(Set.of("metadata", " meta "))
                .build();

        assertEquals("metadata", capability.id());
        assertEquals(WorkflowCapability.DEFAULT_NAMESPACE, capability.namespace());
        assertEquals("", capability.description());
        assertEquals(Version.parse("1.0.0"), capability.version());
        assertEquals(Set.of("meta"), capability.aliases());
        assertThrows(UnsupportedOperationException.class, () -> capability.aliases().add("other"));
    }

    @Test
    void factoryMethodsCreateRequiredAndProducedCapabilities() {
        WorkflowCapability required = WorkflowCapability.required("core", "structured-document", StructuredDocument.class, Version.parse("1.0.0"));
        WorkflowCapability produced = WorkflowCapability.produced("metadata", MetadataDto.class);

        assertTrue(required.required());
        assertFalse(produced.required());
        assertEquals("core:structured-document@1.0.0", required.qualifiedName());
        assertEquals("core:metadata@1.0.0", produced.qualifiedName());
    }

    @Test
    void rejectsMissingIdentityAndType() {
        assertThrows(IllegalArgumentException.class, () -> WorkflowCapability.produced(" ", MetadataDto.class));
        assertThrows(NullPointerException.class, () -> WorkflowCapability.produced("metadata", null));
    }
}

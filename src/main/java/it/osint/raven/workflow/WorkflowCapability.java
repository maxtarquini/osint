package it.osint.raven.workflow;

import java.io.Serializable;
import java.lang.module.ModuleDescriptor.Version;
import java.util.LinkedHashSet;
import java.util.Objects;
import java.util.Set;

/**
 * Immutable domain value object that identifies a workflow capability.
 * <p>
 * A capability is the nominal contract used by Raven workflow nodes and future
 * engines to describe dependencies. It is not the same thing as a Java type.
 * The capability identity is made of {@code namespace}, {@code id} and
 * {@code version}; the Java {@code type} is only runtime metadata used by
 * {@link WorkflowContext} to validate and cast artifact values.
 * <p>
 * For example, {@code osint:entity-extraction@1.0.0} and
 * {@code graph:entity-extraction@1.0.0} are different capabilities even if
 * both validate values with the same Java class. Likewise,
 * {@code osint:entity-extraction@1.0.0} and
 * {@code osint:organization-resolution@1.0.0} are different capabilities even
 * if both are represented by {@code List.class}.
 *
 * @param id stable logical capability identifier, for example {@code structured-document}
 * @param namespace namespace that prevents collisions, for example {@code core} or {@code osint}
 * @param description short human-readable capability description
 * @param type Java value type used only for runtime validation and casting
 * @param version capability contract version
 * @param required true when this declaration describes an input requirement
 * @param aliases alternate logical ids accepted for matching or lookup
 */
public record WorkflowCapability(
        String id,
        String namespace,
        String description,
        Class<?> type,
        Version version,
        boolean required,
        Set<String> aliases
) implements Serializable {

    /**
     * Default namespace used by compatibility factory methods.
     */
    public static final String DEFAULT_NAMESPACE = "core";

    /**
     * Default version used by compatibility factory methods.
     */
    public static final Version DEFAULT_VERSION = Version.parse("1.0.0");

    /**
     * Creates an immutable capability and normalizes optional fields.
     */
    public WorkflowCapability {
        id = requireText(id, "id");
        namespace = namespace == null || namespace.isBlank() ? DEFAULT_NAMESPACE : namespace.trim();
        description = description == null ? "" : description.trim();
        type = Objects.requireNonNull(type, "type must not be null");
        version = version == null ? DEFAULT_VERSION : version;
        aliases = normalizeAliases(aliases, id);
    }

    /**
     * Creates a required input capability with default namespace and version.
     *
     * @param id stable capability identifier
     * @param type Java value type used for validation
     * @return required capability
     */
    public static WorkflowCapability required(String id, Class<?> type) {
        return builder()
                .id(id)
                .type(type)
                .required(true)
                .build();
    }

    /**
     * Creates a required input capability with default namespace and explicit version.
     *
     * @param id stable capability identifier
     * @param type Java value type used for validation
     * @param version capability version
     * @return required capability
     */
    public static WorkflowCapability required(String id, Class<?> type, Version version) {
        return builder()
                .id(id)
                .type(type)
                .version(version)
                .required(true)
                .build();
    }

    /**
     * Creates a required input capability with explicit namespace and version.
     *
     * @param namespace capability namespace
     * @param id stable capability identifier
     * @param type Java value type used for validation
     * @param version capability version
     * @return required capability
     */
    public static WorkflowCapability required(String namespace, String id, Class<?> type, Version version) {
        return builder()
                .namespace(namespace)
                .id(id)
                .type(type)
                .version(version)
                .required(true)
                .build();
    }

    /**
     * Creates a produced output capability with default namespace and version.
     *
     * @param id stable capability identifier
     * @param type Java value type used for validation
     * @return produced capability
     */
    public static WorkflowCapability produced(String id, Class<?> type) {
        return builder()
                .id(id)
                .type(type)
                .required(false)
                .build();
    }

    /**
     * Creates a produced output capability with default namespace and explicit version.
     *
     * @param id stable capability identifier
     * @param type Java value type used for validation
     * @param version capability version
     * @return produced capability
     */
    public static WorkflowCapability produced(String id, Class<?> type, Version version) {
        return builder()
                .id(id)
                .type(type)
                .version(version)
                .required(false)
                .build();
    }

    /**
     * Creates a produced output capability with explicit namespace and version.
     *
     * @param namespace capability namespace
     * @param id stable capability identifier
     * @param type Java value type used for validation
     * @param version capability version
     * @return produced capability
     */
    public static WorkflowCapability produced(String namespace, String id, Class<?> type, Version version) {
        return builder()
                .namespace(namespace)
                .id(id)
                .type(type)
                .version(version)
                .required(false)
                .build();
    }

    /**
     * Creates a builder for a workflow capability.
     *
     * @return capability builder
     */
    public static Builder builder() {
        return new Builder();
    }

    /**
     * Returns the stable qualified capability name used for artifact lookup.
     *
     * @return qualified name in {@code namespace:id@version} form
     */
    public String qualifiedName() {
        return qualifiedName(namespace, id, version);
    }

    /**
     * Checks whether this capability matches another declaration.
     * <p>
     * Matching uses namespace and version plus either the canonical id or one
     * of the declared aliases. Java type is intentionally ignored because the
     * type validates payloads, but does not define the dependency identity.
     *
     * @param other capability to compare
     * @return true when namespace, version and id or aliases match
     */
    public boolean matches(WorkflowCapability other) {
        if (other == null) {
            return false;
        }
        return matches(other.namespace, other.id, other.version)
                || other.aliases.stream().anyMatch(alias -> matches(other.namespace, alias, other.version));
    }

    /**
     * Checks whether this capability matches the supplied nominal coordinates.
     *
     * @param namespace namespace to match
     * @param idOrAlias canonical id or alias to match
     * @param version version to match
     * @return true when the supplied coordinates identify this capability
     */
    public boolean matches(String namespace, String idOrAlias, Version version) {
        if (namespace == null || idOrAlias == null || version == null) {
            return false;
        }
        return this.namespace.equals(namespace.trim())
                && this.version.equals(version)
                && (this.id.equals(idOrAlias.trim()) || supportsAlias(idOrAlias));
    }

    /**
     * Checks whether the supplied value is an alias for this capability.
     *
     * @param alias candidate alias
     * @return true when the alias is declared by this capability
     */
    public boolean supportsAlias(String alias) {
        return alias != null && aliases.contains(alias.trim());
    }

    /**
     * Creates a qualified name for the supplied coordinates.
     *
     * @param namespace capability namespace
     * @param id capability id or alias
     * @param version capability version
     * @return qualified name in {@code namespace:id@version} form
     */
    static String qualifiedName(String namespace, String id, Version version) {
        return requireText(namespace, "namespace") + ":" + requireText(id, "id") + "@" + Objects.requireNonNull(version);
    }

    /**
     * Equality uses only namespace, id and version.
     * <p>
     * Java type, description, aliases and the required/produced direction do
     * not participate in identity.
     *
     * @param other value to compare
     * @return true when namespace, id and version are equal
     */
    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof WorkflowCapability capability)) {
            return false;
        }
        return namespace.equals(capability.namespace)
                && id.equals(capability.id)
                && version.equals(capability.version);
    }

    /**
     * Hash code compatible with {@link #equals(Object)}.
     *
     * @return hash based on namespace, id and version
     */
    @Override
    public int hashCode() {
        return Objects.hash(namespace, id, version);
    }

    private static Set<String> normalizeAliases(Set<String> aliases, String id) {
        if (aliases == null || aliases.isEmpty()) {
            return Set.of();
        }
        LinkedHashSet<String> normalized = new LinkedHashSet<>();
        for (String alias : aliases) {
            if (alias != null && !alias.isBlank()) {
                String candidate = alias.trim();
                if (!candidate.equals(id)) {
                    normalized.add(candidate);
                }
            }
        }
        return Set.copyOf(normalized);
    }

    private static String requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
        return value.trim();
    }

    /**
     * Mutable builder that creates immutable {@link WorkflowCapability} values.
     */
    public static final class Builder {

        private String id;
        private String namespace = DEFAULT_NAMESPACE;
        private String description = "";
        private Class<?> type;
        private Version version = DEFAULT_VERSION;
        private boolean required;
        private Set<String> aliases = Set.of();

        private Builder() {
        }

        public Builder id(String id) {
            this.id = id;
            return this;
        }

        public Builder namespace(String namespace) {
            this.namespace = namespace;
            return this;
        }

        public Builder description(String description) {
            this.description = description;
            return this;
        }

        public Builder type(Class<?> type) {
            this.type = type;
            return this;
        }

        public Builder version(Version version) {
            this.version = version;
            return this;
        }

        public Builder required(boolean required) {
            this.required = required;
            return this;
        }

        public Builder aliases(Set<String> aliases) {
            this.aliases = aliases;
            return this;
        }

        public Builder addAlias(String alias) {
            LinkedHashSet<String> values = new LinkedHashSet<>(this.aliases);
            values.add(alias);
            this.aliases = values;
            return this;
        }

        public WorkflowCapability build() {
            return new WorkflowCapability(id, namespace, description, type, version, required, aliases);
        }
    }
}
